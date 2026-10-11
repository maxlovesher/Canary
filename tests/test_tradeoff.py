import json
import xml.etree.ElementTree as ET

import pytest

from canary.cli import EXIT_OK, main
from canary.metrics.stats import mcnemar_exact
from canary.records import AttackResult, TargetResponse, Verdict
from canary.tradeoff import build_report, format_table, nice_axis, paired_test, render_svg, summarize_condition
from tests.helpers import make_case


def results(successes: list[bool | None], *, blocked: int = 0, prefix: str = "c") -> list[AttackResult]:
    out = []
    for i, success in enumerate(successes):
        out.append(
            AttackResult(
                case=make_case(f"{prefix}{i}"),
                response=TargetResponse(
                    text="placeholder",
                    model="m",
                    latency_ms=100.0 + i,
                    blocked_by="guard: unsafe" if i < blocked else None,
                ),
                verdict=Verdict(success=success, judge="rule", reason="r"),
                secondary_verdicts=[
                    Verdict(success=not success if success is not None else None, judge="llm", reason="r")
                ],
            )
        )
    return out


def test_summarize_condition_rates():
    harmful = results([True, False, False, False], blocked=2)
    benign = results([True, True, True, False], prefix="b")  # 1 of 4 benign refused
    summary = summarize_condition("guard", harmful, benign)
    assert summary["asr"]["rate"] == pytest.approx(0.25)
    assert summary["utility"]["rate"] == pytest.approx(0.75)
    assert summary["false_refusal"]["rate"] == pytest.approx(0.25)
    assert summary["blocked"] == {"harmful": 2, "benign": 0}
    assert summary["latency_ms_p50"]["harmful"] == pytest.approx(101.5)


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [
        (0, 0, 1.0),
        (5, 0, 2 / 2**5),  # all 5 discordant pairs one way: 0.0625
        (1, 9, 2 * (1 + 10) / 2**10),  # 0.021484375
        (10, 10, 1.0),  # symmetric: capped at 1
    ],
)
def test_mcnemar_exact_reference_values(b, c, expected):
    assert mcnemar_exact(b, c) == pytest.approx(expected)
    assert mcnemar_exact(c, b) == pytest.approx(expected)  # two-sided


def test_mcnemar_rejects_negative_counts():
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 2)


def test_paired_test_pairs_by_case_id_and_skips_unjudged():
    baseline = results([True, True, False, None])  # c0..c3
    condition = list(reversed(results([False, True, True, True])))  # order must not matter
    test = paired_test(baseline, condition, lambda r: r.verdict.success)
    # c0: T->F (baseline only), c1: T->T, c2: F->T (condition only), c3: unjudged in baseline
    assert test == {"n_pairs": 3, "baseline_only": 1, "condition_only": 1, "p_value": 1.0}


def test_summarize_condition_with_baseline_reports_paired_tests():
    base_h = results([True] * 6 + [False] * 4)
    base_b = results([True] * 10, prefix="b")
    defended_h = results([False] * 10)  # removes all 6 successes
    defended_b = results([False] * 8 + [True] * 2, prefix="b")  # refuses 8 benign
    summary = summarize_condition("filter", defended_h, defended_b, baseline=(base_h, base_b))
    asr, fr = summary["vs_baseline"]["asr"], summary["vs_baseline"]["false_refusal"]
    assert (asr["baseline_only"], asr["condition_only"]) == (6, 0)
    assert asr["p_value"] == pytest.approx(2 / 2**6)
    assert (fr["baseline_only"], fr["condition_only"]) == (0, 8)
    assert fr["p_value"] == pytest.approx(2 / 2**8)
    assert "vs_baseline" not in summarize_condition("none", base_h, base_b)
    table = format_table(build_report([summarize_condition("none", base_h, base_b), summary], judge=None))
    assert "base" in table and "0.031" in table and "0.008" in table


def test_secondary_judge_can_define_asr():
    harmful = results([True, False, False, False])
    summary = summarize_condition("x", harmful, results([True], prefix="b"), judge="llm")
    assert summary["asr"]["rate"] == pytest.approx(0.75)


def test_report_table_and_svg_are_well_formed():
    report = build_report(
        [
            summarize_condition("none", results([True, False]), results([True, True], prefix="b")),
            summarize_condition("filter <&>", results([False, False]), results([True, False], prefix="b")),
        ],
        judge=None,
    )
    table = format_table(report)
    assert "none" in table and "filter <&>" in table and "50.0%" in table
    svg = render_svg(report)
    root = ET.fromstring(svg)  # valid XML even with special characters in labels
    assert root.tag.endswith("svg")
    assert "filter &lt;&amp;&gt;" in svg
    assert svg.count("<circle") == 4  # 2 points + 2 legend markers


@pytest.mark.parametrize(
    ("values", "limit", "ticks"),
    [
        ([0.772], 1.0, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        ([0.125], 0.15, [0.0, 0.05, 0.1, 0.15]),
        ([0.0], 0.05, [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]),
        ([0.42], 0.5, [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]),
    ],
)
def test_nice_axis_uses_round_ticks(values, limit, ticks):
    got_limit, got_ticks = nice_axis(values)
    assert got_limit == pytest.approx(limit)
    assert got_ticks == pytest.approx(ticks)


def test_svg_handles_empty_conditions():
    report = build_report([summarize_condition("empty", [], [])], judge=None)
    ET.fromstring(render_svg(report))


def test_cli_tradeoff(config_dict, write_config, tmp_path):
    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    run_dir = next((tmp_path / "runs").iterdir())
    out = tmp_path / "report"
    code = main(["tradeoff", "--pair", "none", str(run_dir), str(run_dir), "--out", str(out)])
    assert code == EXIT_OK
    report = json.loads((out / "tradeoff.json").read_text(encoding="utf-8"))
    assert report["conditions"][0]["label"] == "none"
    assert report["provenance"] == "measured"
    ET.fromstring((out / "tradeoff.svg").read_text(encoding="utf-8"))
