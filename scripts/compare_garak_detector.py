"""Head-to-head: garak's MitigationBypass refusal detector vs Canary's judges.

Scores the *same* cached responses with garak's detector (substrings fetched from
garak's source at a pinned commit, matching re-implemented exactly) and reports
pairwise agreement (raw agreement, Cohen's kappa) with every Canary judge that
scored those responses. No model calls, no new attacks, no garak install.

Usage:
    uv run python scripts/compare_garak_detector.py --run runs/<baseline> [--judge-run runs/<rejudge> ...]

Writes reports/garak_comparison/judges.json (aggregates only), which
``canary report`` picks up automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from canary.cli import format_judges
from canary.external.garak_mitigation import PINNED_COMMIT, SOURCE_URL, extract_substrings, is_bypass, top_triggers
from canary.metrics.agreement import inter_judge_agreement
from canary.records import AttackResult, Verdict
from canary.run_store import read_results


def load_source(commit: str, cache_dir: Path) -> str:
    """garak's mitigation.py at ``commit``, cached locally after the first download."""
    cached = cache_dir / commit / "mitigation.py"
    if not cached.is_file():
        with urllib.request.urlopen(SOURCE_URL.format(commit=commit), timeout=30) as response:  # noqa: S310
            data = response.read()
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return cached.read_text(encoding="utf-8")


def garak_results(results: list[AttackResult], substrings: list[str], judge: str) -> list[AttackResult]:
    """Copies of ``results`` whose only verdict is garak's, so they pool by response hash."""
    out = []
    for result in results:
        if result.response is None:
            continue
        verdict = Verdict(
            success=is_bypass(result.response.text, substrings),
            judge=judge,
            reason="no mitigation substring" if is_bypass(result.response.text, substrings) else "mitigation found",
        )
        out.append(result.model_copy(update={"verdict": verdict, "secondary_verdicts": []}))
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the comparison; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="run whose responses garak should score")
    parser.add_argument("--judge-run", type=Path, action="append", default=[], help="re-judged replays to include")
    parser.add_argument("--commit", default=PINNED_COMMIT)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/garak"))
    parser.add_argument("--out", type=Path, default=Path("reports/garak_comparison/judges.json"))
    args = parser.parse_args(argv)

    substrings = extract_substrings(load_source(args.commit, args.cache_dir))
    base = read_results(args.run / "results.jsonl")
    judge = f"garak:MitigationBypass@{args.commit[:7]}"
    others = [read_results(run / "results.jsonl") for run in args.judge_run]
    report = inter_judge_agreement([base, garak_results(base, substrings, judge), *others])
    report["runs"] = [args.run.name, *(run.name for run in args.judge_run)]
    report["garak_commit"] = args.commit
    report["garak_substrings"] = len(substrings)
    report["top_triggers"] = [
        {"substring": s, "responses": n}
        for s, n in top_triggers((r.response.text for r in base if r.response), substrings)
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(format_judges(report))
    print("\nmost frequent garak mitigation substrings (responses containing each):")
    for item in report["top_triggers"]:
        print(f"  {item['responses']:>3}  {item['substring']!r}")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
