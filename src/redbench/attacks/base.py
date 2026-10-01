"""Attack source interface: where attack cases come from."""

from typing import Any, Protocol

from redbench.records import AttackCase
from redbench.registry import Registry


class AttackSource(Protocol):
    """Produces attack cases (a dataset loader now; transforms/attacker LLMs later)."""

    name: str

    def load(self) -> list[AttackCase]:
        """Return the cases in a deterministic order. Raises ``DatasetError``."""
        ...

    def describe(self) -> dict[str, Any]:
        """Provenance for the run manifest (path, content hash, filters). Call after ``load``."""
        ...


ATTACK_SOURCES: Registry[AttackSource] = Registry("attack source")
