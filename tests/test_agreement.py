import pytest

from redbench.labels import Label, response_sha256
from redbench.metrics.agreement import BinaryAgreement, binary_agreement, judge_agreement
from redbench.records import AttackResult, TargetResponse, Verdict
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
