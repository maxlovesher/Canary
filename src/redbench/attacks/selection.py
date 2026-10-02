"""Case selection shared by attack sources: category filter and seeded sampling."""

from __future__ import annotations

import random
from collections.abc import Sequence

from redbench.errors import DatasetError
from redbench.records import AttackCase


def select_cases(
    cases: Sequence[AttackCase],
    *,
    categories: Sequence[str] | None,
    sample: int | None,
    seed: int,
) -> list[AttackCase]:
    """Filter ``cases`` to ``categories`` then draw ``sample`` of them with ``seed``.

    The sample keeps the original order, so the same seed always yields the same
    cases in the same order.

    Raises:
        DatasetError: on unknown categories or a sample larger than the pool.
    """
    selected = list(cases)
    if categories is not None:
        available = sorted({case.category for case in selected})
        unknown = sorted(set(categories) - set(available))
        if unknown:
            raise DatasetError(f"unknown categories {unknown}; available: {available}")
        selected = [case for case in selected if case.category in categories]
    if sample is None:
        return selected
    if sample > len(selected):
        raise DatasetError(f"sample={sample} exceeds the {len(selected)} available cases")
    position = {case.id: index for index, case in enumerate(selected)}
    picked = random.Random(seed).sample(selected, sample)
    return sorted(picked, key=lambda case: position[case.id])
