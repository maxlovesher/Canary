"""Metrics computed from a run's results. All values here are *measured*."""

from collections.abc import Sequence
from typing import Any

from redbench.config import PricingConfig
from redbench.metrics.asr import RateSummary, attack_success_rate
from redbench.metrics.performance import performance_summary
from redbench.records import AttackResult

__all__ = ["RateSummary", "attack_success_rate", "compute_metrics", "performance_summary"]


def compute_metrics(
    results: Sequence[AttackResult],
    *,
    success_definition: str,
    pricing: PricingConfig,
) -> dict[str, Any]:
    """All milestone-1 metrics for one run, as a JSON-ready dict."""
    return {
        "provenance": "measured",
        "success_definition": success_definition,
        "asr": attack_success_rate(results),
        "performance": performance_summary(
            results,
            input_per_mtok=pricing.input_per_mtok,
            output_per_mtok=pricing.output_per_mtok,
        ),
    }
