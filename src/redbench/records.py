"""Typed records passed between components and serialized to ``results.jsonl``."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from redbench.scenario import AgentScenario


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AttackCase(_Record):
    """One attack attempt to send to a target."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)  # attack source type, e.g. "jailbreakbench"
    category: str = Field(min_length=1)
    prompt: str = Field(min_length=1)  # for agent cases: the user's (benign) task
    metadata: dict[str, Any] = Field(default_factory=dict)
    scenario: AgentScenario | None = None  # mock world + attacker goal, for agent targets


class ToolCallRecord(_Record):
    """One tool call an agent made, with the tool's output."""

    step: int = Field(ge=1)
    name: str
    arguments: dict[str, Any]
    output: str


class TargetResponse(_Record):
    """A target's reply to one attack case."""

    text: str  # the final answer; this is what judges see
    model: str
    latency_ms: float = Field(ge=0)  # wall-clock of the original (uncached) call
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None  # e.g. "stop", or "length" when max_tokens cut it off
    reasoning: str | None = None  # separate reasoning trace from thinking models, if any
    trajectory: list[ToolCallRecord] = Field(default_factory=list)  # agent tool calls, in order
    cached: bool = False

    @property
    def truncated(self) -> bool:
        """True when generation stopped because it hit the token limit."""
        return self.finish_reason == "length"


class Verdict(_Record):
    """A judge's decision on whether an attack succeeded."""

    success: bool | None  # None = could not be judged (e.g. the target errored)
    judge: str
    reason: str


class AttackResult(_Record):
    """Everything recorded about one attack case: one line of ``results.jsonl``."""

    case: AttackCase
    response: TargetResponse | None  # None when the target errored
    error: str | None = None
    verdict: Verdict  # from the primary judge; drives ASR
    secondary_verdicts: list[Verdict] = Field(default_factory=list)  # extra judges, reported separately
