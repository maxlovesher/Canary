import json
import xml.etree.ElementTree as ET

import pytest

from redbench.cli import EXIT_OK, main
from redbench.records import AttackResult, TargetResponse, Verdict
from redbench.tradeoff import build_report, format_table, nice_axis, render_svg, summarize_condition
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
