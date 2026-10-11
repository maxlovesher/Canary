"""Defense interface: screens a request before the target and/or a response after it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from canary.records import AttackCase, TargetResponse
from canary.registry import Registry

Stage = Literal["input", "output"]

# What a blocked request "answers". Phrased as a refusal so every judge scores a
# block as a failed attack, and a block of a benign request as a false refusal.
BLOCK_MESSAGE = "I can't help with that request."


@dataclass(frozen=True)
class Screening:
    """Outcome of one defense check."""

    blocked: bool
    reason: str
    latency_ms: float = 0.0


class Defense(Protocol):
    """One guard placed in front of (``input``) or behind (``output``) a target."""

    name: str
    stage: Stage

    def screen(self, case: AttackCase, response: TargetResponse | None) -> Screening:
        """Decide whether to block. ``response`` is None for input-stage defenses."""
        ...

    def describe(self) -> dict[str, Any]:
        """Provenance for the run manifest."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


DEFENSES: Registry[Defense] = Registry("defense")
