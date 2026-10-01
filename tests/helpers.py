"""Test helpers shared across test modules. All data is synthetic placeholder text.

Kept out of conftest.py so test modules can import it without pytest loading the
same module twice (which would register ``ScriptedTarget`` twice).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from redbench.errors import TargetError
from redbench.records import AttackCase, TargetResponse
from redbench.registry import BuildContext, load_builtin_components
from redbench.targets.base import TARGETS

FIXTURES = Path(__file__).parent / "fixtures"
JBB_SAMPLE = FIXTURES / "jbb_sample.csv"

load_builtin_components()


@TARGETS.register("scripted")
class ScriptedTarget:
    """Test target returning canned replies; can fail or interrupt on chosen case IDs."""

    class Params(BaseModel):
        model_config = ConfigDict(extra="forbid")

        replies: dict[str, str] = Field(default_factory=dict)
        default_reply: str = "Sure, here is a placeholder answer."
        fail_ids: list[str] = Field(default_factory=list)
        interrupt_ids: list[str] = Field(default_factory=list)

    name = "scripted"

    def __init__(self, params: Params, context: BuildContext) -> None:
        self.params = params
        self.calls: list[str] = []
        self.closed = False

    def describe(self) -> dict[str, Any]:
        return {"type": self.name}

    def generate(self, case: AttackCase) -> TargetResponse:
        self.calls.append(case.id)
        if case.id in self.params.interrupt_ids:
            raise KeyboardInterrupt
        if case.id in self.params.fail_ids:
            raise TargetError(f"scripted failure for {case.id}")
        text = self.params.replies.get(case.id, self.params.default_reply)
        return TargetResponse(text=text, model="scripted", latency_ms=10.0, input_tokens=5, output_tokens=7)

    def close(self) -> None:
        self.closed = True


def make_case(case_id: str = "c1", category: str = "Category A", prompt: str = "placeholder") -> AttackCase:
    """Build an AttackCase with sensible defaults."""
    return AttackCase(id=case_id, source="test", category=category, prompt=prompt)
