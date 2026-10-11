"""Wraps a target with input- and output-stage defenses."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from canary.defenses.base import BLOCK_MESSAGE, Defense
from canary.records import AttackCase, TargetResponse
from canary.targets.base import Target


class DefendedTarget:
    """A target behind defenses. Looks like any other target to the runner.

    Input defenses run in order before the target; the first block skips the
    target entirely. Output defenses run in order on the target's response; the
    first block replaces the answer with ``BLOCK_MESSAGE``. ``blocked_by`` on the
    response records which defense fired. Latency includes the defenses' time.
    """

    def __init__(self, target: Target, defenses: Sequence[Defense]) -> None:
        self.inner = target
        self.input_defenses = [d for d in defenses if d.stage == "input"]
        self.output_defenses = [d for d in defenses if d.stage == "output"]
        self.name = f"{target.name}+defended"

    def describe(self) -> dict[str, Any]:
        """Inner target plus every defense, for the manifest."""
        return {
            **self.inner.describe(),
            "defenses": [d.describe() for d in (*self.input_defenses, *self.output_defenses)],
        }

    def generate(self, case: AttackCase) -> TargetResponse:
        """Screen the request, call the target, screen the response."""
        overhead_ms = 0.0
        for defense in self.input_defenses:
            screening = defense.screen(case, None)
            overhead_ms += screening.latency_ms
            if screening.blocked:
                return TargetResponse(
                    text=BLOCK_MESSAGE,
                    model=f"defense:{defense.name}",
                    latency_ms=overhead_ms,
                    finish_reason="blocked",
                    blocked_by=f"{defense.name}: {screening.reason}",
                )
        response = self.inner.generate(case)
        for defense in self.output_defenses:
            screening = defense.screen(case, response)
            overhead_ms += screening.latency_ms
            if screening.blocked:
                return response.model_copy(
                    update={
                        "text": BLOCK_MESSAGE,
                        "latency_ms": response.latency_ms + overhead_ms,
                        "finish_reason": "blocked",
                        "blocked_by": f"{defense.name}: {screening.reason}",
                    }
                )
        if overhead_ms:
            return response.model_copy(update={"latency_ms": response.latency_ms + overhead_ms})
        return response

    def close(self) -> None:
        """Close the target and every defense."""
        self.inner.close()
        for defense in (*self.input_defenses, *self.output_defenses):
            defense.close()
