"""Attack success rate (ASR), overall and per category, with Wilson 95% intervals.

Unjudged results (``verdict.success is None``: target errors, or answers cut off
by the token limit) are excluded from the denominator and counted separately, so
infrastructure failures never masquerade as successful defenses or attacks.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from redbench.metrics.stats import wilson_interval
from redbench.records import AttackResult


@dataclass(frozen=True)
class RateSummary:
    """A proportion with its Wilson 95% interval; rate fields are None when n == 0."""

    successes: int
    n: int
    rate: float | None
    ci95_low: float | None
    ci95_high: float | None

    @classmethod
    def from_counts(cls, successes: int, n: int) -> "RateSummary":
        """Build from raw counts."""
        if n == 0:
            return cls(successes=0, n=0, rate=None, ci95_low=None, ci95_high=None)
        low, high = wilson_interval(successes, n)
        return cls(successes=successes, n=n, rate=successes / n, ci95_low=low, ci95_high=high)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict."""
        return asdict(self)


def attack_success_rate(results: Sequence[AttackResult]) -> dict[str, Any]:
    """ASR overall and by category, plus the count of unjudged results."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # category -> [successes, n]
    unjudged = 0
    for result in results:
        success = result.verdict.success
        if success is None:
            unjudged += 1
            continue
        bucket = counts[result.case.category]
        bucket[0] += int(success)
        bucket[1] += 1
    total_successes = sum(s for s, _ in counts.values())
    total_n = sum(n for _, n in counts.values())
    return {
        "overall": RateSummary.from_counts(total_successes, total_n).to_dict(),
        "by_category": {cat: RateSummary.from_counts(s, n).to_dict() for cat, (s, n) in sorted(counts.items())},
        "n_results": len(results),
        "n_unjudged": unjudged,
    }
