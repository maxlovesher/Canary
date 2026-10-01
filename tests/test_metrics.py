import itertools

import pytest

from redbench.config import PricingConfig
from redbench.metrics import compute_metrics
from redbench.metrics.asr import RateSummary, attack_success_rate
from redbench.metrics.performance import performance_summary
from redbench.metrics.stats import percentile, wilson_interval
from redbench.records import AttackResult, TargetResponse, Verdict
from tests.helpers import make_case

_ids = itertools.count()


def result(
    category: str,
    success: bool | None,
    latency: float = 100.0,
    cached: bool = False,
    tokens=(10, 20),
    finish_reason: str | None = "stop",
) -> AttackResult:
    response = None
    if success is not None:
        response = TargetResponse(
            text="t",
            model="m",
            latency_ms=latency,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            cached=cached,
            finish_reason=finish_reason,
        )
    return AttackResult(
        case=make_case(case_id=f"{category}-{next(_ids)}", category=category),
        response=response,
        error=None if success is not None else "boom",
        verdict=Verdict(success=success, judge="j", reason="r"),
    )


# Reference values computed independently from the Wilson formula.
@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (5, 10, 0.236593, 0.763407),
        (0, 10, 0.0, 0.277540),
        (10, 10, 0.722460, 1.0),
        (1, 100, 0.001767, 0.054488),
    ],
)
def test_wilson_interval_reference_values(k, n, low, high):
    lo, hi = wilson_interval(k, n)
    assert lo == pytest.approx(low, abs=1e-5)
    assert hi == pytest.approx(high, abs=1e-5)


@pytest.mark.parametrize(("k", "n"), [(0, 0), (-1, 5), (6, 5)])
def test_wilson_interval_rejects_bad_counts(k, n):
    with pytest.raises(ValueError):
        wilson_interval(k, n)


def test_percentile_matches_numpy_linear():
    values = [15.0, 20.0, 35.0, 40.0, 50.0]
    assert percentile(values, 0) == 15.0
    assert percentile(values, 50) == 35.0
    assert percentile(values, 100) == 50.0
    assert percentile(values, 40) == pytest.approx(29.0)  # numpy.percentile(values, 40)
    assert percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_asr_overall_by_category_and_unjudged():
    results = [
        result("A", True),
        result("A", False),
        result("A", True),
        result("B", False),
        result("B", None),  # target error: excluded from denominator
    ]
    asr = attack_success_rate(results)
    assert asr["overall"]["successes"] == 2 and asr["overall"]["n"] == 4
    assert asr["overall"]["rate"] == pytest.approx(0.5)
    assert asr["by_category"]["A"]["rate"] == pytest.approx(2 / 3)
    assert asr["by_category"]["B"]["n"] == 1
    assert asr["n_unjudged"] == 1 and asr["n_results"] == 5
    assert list(asr["by_category"]) == ["A", "B"]


def test_rate_summary_empty():
    assert RateSummary.from_counts(0, 0).rate is None
    assert attack_success_rate([])["overall"]["rate"] is None


def test_performance_summary():
    results = [
        result("A", True, latency=100.0, tokens=(10, 20), finish_reason="length"),
        result("A", False, latency=300.0, cached=True, tokens=(30, 40)),
        result("A", None),
    ]
    perf = performance_summary(results, input_per_mtok=1.0, output_per_mtok=2.0)
    assert perf["n_responses"] == 2 and perf["n_cached"] == 1 and perf["n_truncated"] == 1
    assert perf["latency_ms"]["mean"] == pytest.approx(200.0)
    assert perf["latency_ms"]["p50"] == pytest.approx(200.0)
    assert perf["tokens"] == {"input": 40, "output": 60, "n_missing_token_counts": 0}
    assert perf["cost_usd"]["total"] == pytest.approx((40 * 1.0 + 60 * 2.0) / 1e6)


def test_performance_summary_missing_tokens_and_no_responses():
    perf = performance_summary([result("A", True, tokens=(None, 5))])
    assert perf["tokens"]["n_missing_token_counts"] == 1
    empty = performance_summary([result("A", None)])
    assert empty["latency_ms"] is None and empty["cost_usd"]["per_attack"] is None


def test_compute_metrics_labels_provenance_and_definition():
    metrics = compute_metrics([result("A", True)], success_definition="proxy_non_refusal", pricing=PricingConfig())
    assert metrics["provenance"] == "measured"
    assert metrics["success_definition"] == "proxy_non_refusal"
    assert metrics["asr"]["overall"]["rate"] == 1.0
