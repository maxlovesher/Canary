"""Command-line interface: ``redbench validate`` and ``redbench run``."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from redbench.config import RedBenchConfig, load_config
from redbench.errors import RedBenchError
from redbench.experiment import run_experiment
from redbench.factory import build_components
from redbench.logging_setup import configure_logging
from redbench.runner import Runner

logger = logging.getLogger("redbench")

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        config = load_config(args.config, args.overrides)
        if args.command == "validate":
            return _validate(config)
        return _run(config)
    except RedBenchError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR


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
