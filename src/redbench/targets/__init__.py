"""Targets. Importing this package registers the built-in targets."""

from redbench.targets import ollama_chat as _ollama_chat  # noqa: F401  (registers "ollama_chat")
from redbench.targets.base import TARGETS, Target

__all__ = ["TARGETS", "Target"]
