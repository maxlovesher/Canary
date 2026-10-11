"""Small statistics helpers, implemented here rather than pulled from a library."""

import math
from collections.abc import Sequence

Z_95 = 1.959963984540054  # two-sided 95% normal quantile


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for paired binary outcomes.

    ``b`` and ``c`` are the discordant pair counts (outcome only under A, only
    under B). Under the null hypothesis each discordant pair is equally likely to
    fall either way, so ``p = 2 * P(X <= min(b, c))`` for ``X ~ Binomial(b + c, 1/2)``,
    capped at 1. Exact, so valid for the small counts typical of per-defense deltas.

    Raises:
        ValueError: on negative counts.
    """
    if b < 0 or c < 0:
        raise ValueError(f"discordant counts must be >= 0, got b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal (Wald) interval because it stays inside [0, 1] and
    behaves sensibly at small n and at rates near 0 or 1, which is exactly the
    regime of per-category ASR (JailbreakBench has 10 behaviors per category).

    Raises:
        ValueError: if ``n <= 0`` or ``successes`` is outside ``[0, n]``.
    """
    if n <= 0:
        raise ValueError("wilson_interval needs n > 0")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, {n}], got {successes}")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values: Sequence[float], q: float) -> float:
    """``q``-th percentile (0-100) with linear interpolation between closest ranks.

    Matches numpy's default ("linear") method.

    Raises:
        ValueError: on empty input or ``q`` outside [0, 100].
    """
    if not values:
        raise ValueError("percentile of empty sequence")
    if not 0 <= q <= 100:
        raise ValueError(f"q must be in [0, 100], got {q}")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)
