"""Judge interface: decides whether an attack succeeded."""

from typing import Protocol

from redbench.records import AttackCase, TargetResponse, Verdict
from redbench.registry import Registry


class Judge(Protocol):
    """Turns a (case, response) pair into a ``Verdict``."""

    name: str
    # What "success" means for this judge, copied into metrics so a proxy
    # metric can never be mistaken for a validated one.
    success_definition: str

    def judge(self, case: AttackCase, response: TargetResponse) -> Verdict:
        """Judge one response. Only called when the target produced a response."""
        ...


JUDGES: Registry[Judge] = Registry("judge")
