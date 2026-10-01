"""Target interface: the LLM system under attack."""

from typing import Any, Protocol

from redbench.records import AttackCase, TargetResponse
from redbench.registry import Registry


class Target(Protocol):
    """Something that answers an attack case (plain LLM, RAG pipeline, agent, ...)."""

    name: str

    def describe(self) -> dict[str, Any]:
        """Provenance for the run manifest (model, digest, settings). May contact the backend."""
        ...

    def generate(self, case: AttackCase) -> TargetResponse:
        """Respond to one case. Raises ``TargetError`` on backend failure."""
        ...

    def close(self) -> None:
        """Release network clients or other resources."""
        ...


TARGETS: Registry[Target] = Registry("target")
