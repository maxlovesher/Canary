import json

import pytest

from canary.labels import Label, response_sha256
from canary.metrics.agreement import BinaryAgreement, binary_agreement, inter_judge_agreement, judge_agreement
from canary.records import AttackResult, TargetResponse, Verdict
from tests.helpers import make_case


def test_cohen_kappa_reference_value():
    # Textbook example: 50 items, p_o = 0.7, p_e = 0.5 -> kappa = 0.4
    agreement = BinaryAgreement(tp=20, fp=10, fn=5, tn=15)
    assert agreement.accuracy == pytest.approx(0.7)
    assert agreement.cohen_kappa == pytest.approx(0.4)
    assert agreement.precision == pytest.approx(20 / 30)
    assert agreement.recall == pytest.approx(20 / 25)


def test_perfect_and_chance_level_agreement():
    assert BinaryAgreement(tp=5, fp=0, fn=0, tn=5).cohen_kappa == pytest.approx(1.0)
    # Judge says "yes" to everything on a 50/50 set: accuracy 0.5, kappa 0.
    assert BinaryAgreement(tp=5, fp=5, fn=0, tn=0).cohen_kappa == pytest.approx(0.0)


def test_undefined_values_are_none():
    empty = BinaryAgreement(0, 0, 0, 0)
    assert empty.accuracy is None and empty.cohen_kappa is None
    assert empty.to_dict()["accuracy_ci95"] == [None, None]
    all_negative = BinaryAgreement(tp=0, fp=0, fn=0, tn=10)  # both raters: always "no"
    assert all_negative.accuracy == 1.0
    assert all_negative.cohen_kappa is None
    assert all_negative.precision is None and all_negative.recall is None


def test_binary_agreement_counts_pairs():
    agreement = binary_agreement([(True, True), (True, False), (False, True), (False, False), (False, False)])
    assert (agreement.tp, agreement.fp, agreement.fn, agreement.tn) == (1, 1, 1, 2)


def _result(case_id: str, text: str, success: bool | None, judge: str = "rule") -> AttackResult:
    return AttackResult(
        case=make_case(case_id),
        response=TargetResponse(text=text, model="m", latency_ms=1),
        verdict=Verdict(success=success, judge=judge, reason="r"),
    )


def _label(result: AttackResult, value: str) -> Label:
    assert result.response is not None
    return Label(
        case_id=result.case.id,
        label=value,
        response_sha256=response_sha256(result.response),
        labeled_at="2026-10-03T00:00:00+00:00",
    )


def test_judge_agreement_against_both_ground_truths():
    results = [
        _result("c1", "placeholder a", True),  # judge: success; human: harmful
        _result("c2", "placeholder b", True),  # judge: success; human: safe compliance
        _result("c3", "placeholder c", False),  # judge: refusal; human: refusal
        _result("c4", "placeholder d", None),  # unjudged: excluded from comparisons
    ]
    labels = {
        "c1": _label(results[0], "harmful_compliance"),
        "c2": _label(results[1], "safe_compliance"),
        "c3": _label(results[2], "refusal"),
        "c4": _label(results[3], "refusal"),
    }
    report = judge_agreement(results, labels)
    assert report["n_matched"] == 4
    assert report["label_counts"] == {"refusal": 2, "safe_compliance": 1, "harmful_compliance": 1}
    assert report["human_asr"]["successes"] == 1 and report["human_asr"]["n"] == 4

    rule = report["judges"]["rule"]
    harmful = rule["vs_harmful_compliance"]
    assert harmful["n"] == 3
    assert harmful["confusion"] == {"tp": 1, "fp": 1, "fn": 0, "tn": 1}
    compliance = rule["vs_any_compliance"]
    assert compliance["confusion"] == {"tp": 2, "fp": 0, "fn": 0, "tn": 1}
    assert compliance["accuracy"] == 1.0


def test_stale_and_unknown_labels_are_excluded():
    result = _result("c1", "placeholder now", True)
    stale = Label(
        case_id="c1",
        label="refusal",
        response_sha256=response_sha256(TargetResponse(text="placeholder before", model="m", latency_ms=1)),
        labeled_at="2026-10-03T00:00:00+00:00",
    )
    unknown = _label(_result("zz", "placeholder", True), "refusal")
    report = judge_agreement([result], {"c1": stale, "zz": unknown})
    assert report["n_matched"] == 0 and report["n_stale"] == 1 and report["n_unknown_case"] == 1
    assert report["human_asr"]["rate"] is None


def test_inter_judge_agreement_pools_runs_by_response():
    # Run 1: rule judge. Run 2: same responses re-judged by an LLM judge.
    texts = ["placeholder a", "placeholder b", "placeholder c", "placeholder d"]
    rule = [True, False, False, False]
    llm = [False, False, False, True]
    run1 = [_result(f"c{i}", t, s, judge="rule") for i, (t, s) in enumerate(zip(texts, rule, strict=True))]
    run2 = [_result(f"c{i}", t, s, judge="llm") for i, (t, s) in enumerate(zip(texts, llm, strict=True))]
    run2.append(_result("c9", "only in run 2", True, judge="llm"))  # no partner verdict: not paired
    report = inter_judge_agreement([run1, run2])
    assert report["judges"] == ["llm", "rule"]
    assert report["positives"] == {"llm": 2, "rule": 1}
    (pair,) = report["pairs"]
    assert (pair["a"], pair["b"], pair["n"]) == ("llm", "rule", 4)
    assert (pair["both"], pair["a_only"], pair["b_only"]) == (0, 1, 1)
    assert pair["agreement"] == pytest.approx(0.5)
    # p_o = 0.5; p_e = 0.25*0.25 + 0.75*0.75 = 0.625 -> kappa = (0.5-0.625)/0.375
    assert pair["cohen_kappa"] == pytest.approx(-1 / 3)


def test_inter_judge_agreement_ignores_different_responses_for_same_case():
    run1 = [_result("c1", "placeholder old", True, judge="rule")]
    run2 = [_result("c1", "placeholder new", True, judge="llm")]
    assert inter_judge_agreement([run1, run2])["pairs"][0]["n"] == 0


def test_cli_judges_writes_report(config_dict, write_config, tmp_path):
    from canary.cli import EXIT_OK, main

    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    run_dir = next((tmp_path / "runs").iterdir())
    out = tmp_path / "j" / "judges.json"
    assert main(["judges", str(run_dir), "--out", str(out)]) == EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["judges"] == ["refusal_patterns"] and report["pairs"] == []
    assert report["runs"] == [run_dir.name]


def test_secondary_judges_are_scored_too():
    result = AttackResult(
        case=make_case("c1"),
        response=TargetResponse(text="placeholder", model="m", latency_ms=1),
        verdict=Verdict(success=True, judge="rule", reason="r"),
        secondary_verdicts=[Verdict(success=False, judge="other", reason="r")],
    )
    report = judge_agreement([result], {"c1": _label(result, "refusal")})
    assert set(report["judges"]) == {"rule", "other"}
    assert report["judges"]["other"]["vs_harmful_compliance"]["confusion"]["tn"] == 1
