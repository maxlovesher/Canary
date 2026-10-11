"""Judges. Importing this package registers the built-in judges."""

from canary.judges import llm_judge as _llm_judge  # noqa: F401  (registers "ollama_llm_judge")
from canary.judges import refusal_patterns as _refusal_patterns  # noqa: F401  (registers "refusal_patterns")
from canary.judges.base import JUDGES, Judge

__all__ = ["JUDGES", "Judge"]
