"""Command-line interface: ``redbench validate | run | label | agreement``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from redbench.config import RedBenchConfig, load_config
from redbench.errors import RedBenchError
from redbench.experiment import run_experiment
from redbench.factory import build_components
from redbench.labeling import run_labeling
from redbench.labels import LabelStore
from redbench.logging_setup import configure_logging
from redbench.metrics.agreement import judge_agreement
from redbench.records import AttackResult
from redbench.run_store import RunStore, read_results
from redbench.runner import Runner

logger = logging.getLogger("redbench")

AGREEMENT_FILE = "agreement.json"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``redbench`` command."""
    parser = argparse.ArgumentParser(prog="redbench", description="Automated red-teaming harness for LLM systems.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "check a config and load its attack cases without calling any model"),
        ("run", "run an experiment and write results to a new run directory"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("config", type=Path, help="path to a YAML config")
        command.add_argument(
            "--set",
            dest="overrides",
            action="append",
            default=[],
            metavar="KEY=VALUE",
            help="override a config value, e.g. --set target.params.model=qwen3:4b (repeatable)",
        )
    label = commands.add_parser("label", help="hand-label a run's responses (blind, resumable)")
    label.add_argument("run_dir", type=Path, help="run directory containing results.jsonl")
    label.add_argument("--labeler", default=None, help="your name or initials, stored with each label")
    label.add_argument("--relabel", action="store_true", help="revisit cases that already have a label")
    label.add_argument("--show-reasoning", action="store_true", help="also show the model's reasoning trace")
    agreement = commands.add_parser("agreement", help="score the run's judges against its human labels")
    agreement.add_argument("run_dir", type=Path, help="run directory containing results.jsonl")
    agreement.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="labels.jsonl to use (default: the run's own). Labels from another run apply only where the "
        "response text is identical, e.g. a re-judged replay of the same responses.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        if args.command == "label":
            return _label(args.run_dir, labeler=args.labeler, relabel=args.relabel, show_reasoning=args.show_reasoning)
        if args.command == "agreement":
            return _agreement(args.run_dir, labels_path=args.labels)
        config = load_config(args.config, args.overrides)
        if args.command == "validate":
            return _validate(config)
        return _run(config)
    except RedBenchError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR


def _load_run_results(run_dir: Path) -> list[AttackResult]:
    path = run_dir / RunStore.RESULTS_FILE
    if not path.is_file():
        raise RedBenchError(f"no {RunStore.RESULTS_FILE} in {run_dir}; is this a run directory?")
    try:
        return read_results(path)
    except (OSError, ValidationError) as exc:
        raise RedBenchError(f"cannot read {path}: {exc}") from exc


def _label(run_dir: Path, *, labeler: str | None, relabel: bool, show_reasoning: bool) -> int:
    results = _load_run_results(run_dir)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # model output may not fit the console encoding
    store = LabelStore.for_run(run_dir)
    summary = run_labeling(results, store, labeler=labeler, relabel=relabel, show_reasoning=show_reasoning)
    print(
        f"\nlabeled {summary.labeled}, skipped {summary.skipped}, remaining {summary.remaining}; "
        f"labels saved in {store.path}"
    )
    return EXIT_OK


def _agreement(run_dir: Path, *, labels_path: Path | None = None) -> int:
    results = _load_run_results(run_dir)
    store = LabelStore(labels_path) if labels_path is not None else LabelStore.for_run(run_dir)
    labels = store.load()
    if not labels:
        raise RedBenchError(f"no labels in {store.path}; run `redbench label <run_dir>` first")
    report = judge_agreement(results, labels)
    RunStore(run_dir).write_json(AGREEMENT_FILE, report)
    print(format_agreement(report))
    print(f"\nwritten to {run_dir / AGREEMENT_FILE}")
    return EXIT_OK


def format_agreement(report: dict[str, Any]) -> str:
    """Human-readable judge-vs-human agreement report."""
    counts = report["label_counts"]
    human = report["human_asr"]
    lines = [
        f"Judge agreement with human labels ({report['provenance']})",
        f"labels matched: {report['n_matched']} (stale: {report['n_stale']}, unknown case: {report['n_unknown_case']})",
        "label counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()),
        f"human ASR (harmful_compliance): {human['n']:>4} {_fmt_rate(human)}",
    ]
    for name, scores in report["judges"].items():
        lines.append(f"\njudge {name}")
        for truth in ("vs_harmful_compliance", "vs_any_compliance"):
            s = scores[truth]
            c = s["confusion"]
            kappa = _fmt_opt(s["cohen_kappa"], pct=False)
            lines.append(
                f"  {truth:<22} n={s['n']:<4} acc={_fmt_opt(s['accuracy'])} kappa={kappa} "
                f"precision={_fmt_opt(s['precision'])} recall={_fmt_opt(s['recall'])}  "
                f"TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}"
            )
    return "\n".join(lines)


def _fmt_opt(value: float | None, *, pct: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}" if pct else f"{value:.2f}"


def _validate(config: RedBenchConfig) -> int:
    components = build_components(config, cache=None)
    try:
        runner = Runner(components.target, components.sources, components.judge, max_cases=config.run.max_cases)
        cases = runner.load_cases()
    finally:
        components.close()
    categories = sorted({case.category for case in cases})
    print(
        f"config OK: target={config.target.type}, judge={config.judge.type}, "
        f"{len(cases)} cases across {len(categories)} categories"
    )
    return EXIT_OK


def _run(config: RedBenchConfig) -> int:
    summary = run_experiment(config)
    print(format_asr_table(summary.metrics))
    print(f"\nrun directory: {summary.run_dir}")
    return EXIT_INTERRUPTED if summary.interrupted else EXIT_OK


def format_asr_table(metrics: dict[str, Any]) -> str:
    """Human-readable ASR table for the terminal."""
    asr = metrics["asr"]
    lines = [
        f"ASR [{metrics['success_definition']}] ({metrics['provenance']})",
        f"{'category':<32} {'n':>4} {'ASR':>7}   95% CI",
    ]
    rows = [*asr["by_category"].items(), ("OVERALL", asr["overall"])]
    for category, summary in rows:
        lines.append(f"{category[:32]:<32} {summary['n']:>4} {_fmt_rate(summary)}")
    lines.append(f"unjudged (target errors / truncated answers): {asr['n_unjudged']} of {asr['n_results']}")
    for name, secondary in metrics.get("secondary_asr", {}).items():
        overall = secondary["asr"]["overall"]
        lines.append(f"secondary {name} [{secondary['success_definition']}]: {overall['n']:>4} {_fmt_rate(overall)}")
    truncated = metrics["performance"]["n_truncated"]
    if truncated:
        lines.append(f"WARNING: {truncated} responses hit max_tokens; consider raising target.params.max_tokens")
    return "\n".join(lines)


def _fmt_rate(summary: dict[str, Any]) -> str:
    if summary["rate"] is None:
        return f"{'n/a':>7}"
    return f"{summary['rate']:>7.1%}   [{summary['ci95_low']:.1%}, {summary['ci95_high']:.1%}]"


if __name__ == "__main__":
    raise SystemExit(main())
