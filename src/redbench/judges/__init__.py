"""Judges. Importing this package registers the built-in judges."""

from redbench.judges import refusal_patterns as _refusal_patterns  # noqa: F401  (registers "refusal_patterns")
from redbench.judges.base import JUDGES, Judge

__all__ = ["JUDGES", "Judge"]
