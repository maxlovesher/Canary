"""Llama Guard helpers shared by the LLM judge and the guard-filter defense.

Llama Guard's Ollama chat template turns a conversation into its moderation
prompt and classifies the *last* turn: a user-only conversation classifies the
request, a user+assistant conversation classifies the response. It answers
``safe`` or ``unsafe\\n<category codes>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardDecision:
    """Parsed Llama Guard output; ``unsafe`` is None when the output is unparseable."""

    unsafe: bool | None
    category: str | None
    raw: str


def guard_messages(request: str, response: str | None = None) -> list[dict[str, str]]:
    """Conversation to classify: the request alone, or the request plus a response."""
    messages = [{"role": "user", "content": request}]
    if response is not None:
        messages.append({"role": "assistant", "content": response})
    return messages


def parse_guard_output(output: str) -> GuardDecision:
    """Parse ``safe`` / ``unsafe\\nS1,S2`` (case-insensitive, surrounding whitespace ignored).

    A bare category list (``S6``) counts as unsafe: Llama Guard 3 1B occasionally
    omits the ``unsafe`` line (observed 2026-10-03), and categories only accompany
    unsafe verdicts.
    """
    first, _, rest = output.strip().partition("\n")
    verdict = first.strip().lower()
    if verdict == "unsafe":
        return GuardDecision(unsafe=True, category=rest.strip() or None, raw=output)
    if verdict == "safe":
        return GuardDecision(unsafe=False, category=None, raw=output)
    if _CATEGORIES.fullmatch(first.strip()):
        return GuardDecision(unsafe=True, category=first.strip(), raw=output)
    return GuardDecision(unsafe=None, category=None, raw=output)


_CATEGORIES = re.compile(r"S\d{1,2}(\s*,\s*S\d{1,2})*", re.IGNORECASE)
