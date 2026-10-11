"""Small statistics helpers, implemented here rather than pulled from a library."""

import math
from collections.abc import Sequence

Z_95 = 1.959963984540054  # two-sided 95% normal quantile


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
