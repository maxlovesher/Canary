"""Latency, token usage, and cost metrics."""

from collections.abc import Sequence
from typing import Any

from redbench.metrics.stats import percentile
from redbench.records import AttackResult


def performance_summary(
    results: Sequence[AttackResult],
    *,
    input_per_mtok: float = 0.0,
    output_per_mtok: float = 0.0,
) -> dict[str, Any]:
    """Summarize latency, tokens and cost over results that got a response.

    Latency is the original call's wall-clock time even for cache hits, so a
    replayed run reports the same latency as the run that produced the cache.
    Missing token counts are treated as 0 and reported in ``n_missing_token_counts``.
    """
    responses = [r.response for r in results if r.response is not None]
    latencies = [resp.latency_ms for resp in responses]
    input_tokens = sum(resp.input_tokens or 0 for resp in responses)
    output_tokens = sum(resp.output_tokens or 0 for resp in responses)
    missing = sum(1 for resp in responses if resp.input_tokens is None or resp.output_tokens is None)
    cost = (input_tokens * input_per_mtok + output_tokens * output_per_mtok) / 1_000_000
    latency: dict[str, float] | None = None
    if latencies:
        latency = {
            "mean": sum(latencies) / len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "max": max(latencies),
        }
    return {
        "n_responses": len(responses),
        "n_cached": sum(1 for resp in responses if resp.cached),
        "n_truncated": sum(1 for resp in responses if resp.truncated),  # hit max_tokens
        "latency_ms": latency,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "n_missing_token_counts": missing,
        },
        "cost_usd": {
            "total": cost,
            "per_attack": cost / len(responses) if responses else None,
        },
    }
