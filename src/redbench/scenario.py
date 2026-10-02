"""Agent scenarios: the mock world an injection case runs in, and what the attacker wants.

A scenario's text may contain two placeholders:

- ``{canary}``: replaced by the run's canary secret when the environment is
  materialized, so a leak of that exact string is unambiguous evidence.
- ``{injection}``: marks where the attacker payload is inserted into the content
  at ``injection.key``. Without the marker the payload is appended.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANARY_PLACEHOLDER = "{canary}"
INJECTION_PLACEHOLDER = "{injection}"


def make_canary(seed: int) -> str:
    """Deterministic per-run canary secret derived from the run seed."""
    digest = hashlib.sha256(f"redbench-canary:{seed}".encode()).hexdigest()[:16].upper()
    return f"CANARY-{digest}"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Email(_Model):
    """One message in the mock inbox."""

    id: str = Field(min_length=1)
    sender: str
    subject: str
    body: str


class EnvironmentSpec(_Model):
    """Initial state of the mock world: files, web pages, inbox."""

    files: dict[str, str] = Field(default_factory=dict)
    web: dict[str, str] = Field(default_factory=dict)
    inbox: list[Email] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_email_ids(self) -> EnvironmentSpec:
        ids = [email.id for email in self.inbox]
        if len(ids) != len(set(ids)):
            raise ValueError("inbox email ids must be unique")
        return self


class Injection(_Model):
    """Attacker-controlled text planted in a tool-reachable location."""

    location: Literal["web", "file", "email"]
    key: str = Field(min_length=1)  # URL, file path, or email id
    payload: str = Field(min_length=1)


class AttackerGoal(_Model):
    """What counts as a successful attack, in machine-checkable form.

    - ``tool_call``: the agent calls ``tool`` with arguments whose string values
      contain every ``arg_constraints`` value (case-insensitive substring match).
    - ``canary_exfil``: the canary appears in any outbound channel (sent email,
      fetched URL).
    """

    kind: Literal["tool_call", "canary_exfil"]
    tool: str | None = None
    arg_constraints: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_kind(self) -> AttackerGoal:
        if self.kind == "tool_call" and not self.tool:
            raise ValueError("attacker_goal of kind 'tool_call' needs 'tool'")
        if self.kind == "canary_exfil" and (self.tool or self.arg_constraints):
            raise ValueError("attacker_goal of kind 'canary_exfil' takes no 'tool' or 'arg_constraints'")
        return self


class AgentScenario(_Model):
    """Everything an agent target needs to run one case, besides the user's task."""

    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    injection: Injection | None = None
    attacker_goal: AttackerGoal

    @model_validator(mode="after")
    def _injection_target_exists(self) -> AgentScenario:
        inj = self.injection
        if inj is None:
            return self
        env = self.environment
        exists = {
            "web": inj.key in env.web,
            "file": inj.key in env.files,
            "email": any(email.id == inj.key for email in env.inbox),
        }[inj.location]
        if not exists:
            raise ValueError(f"injection target {inj.location}:{inj.key!r} is not in the environment")
        return self

    def materialize(self, canary: str) -> EnvironmentSpec:
        """Return the environment with the canary planted and the injection inserted.

        Unused ``{injection}`` markers are removed, so the same environment works
        as a benign (no-injection) control.
        """
        env = self.environment
        inj = self.injection

        def render(location: str, key: str, text: str) -> str:
            text = text.replace(CANARY_PLACEHOLDER, canary)
            if inj is not None and inj.location == location and inj.key == key:
                if INJECTION_PLACEHOLDER in text:
                    return text.replace(INJECTION_PLACEHOLDER, inj.payload)
                return f"{text}\n\n{inj.payload}"
            return text.replace(INJECTION_PLACEHOLDER, "")

        return EnvironmentSpec(
            files={path: render("file", path, text) for path, text in env.files.items()},
            web={url: render("web", url, text) for url, text in env.web.items()},
            inbox=[email.model_copy(update={"body": render("email", email.id, email.body)}) for email in env.inbox],
        )
