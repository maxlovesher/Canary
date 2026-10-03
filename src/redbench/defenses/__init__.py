"""Defenses. Importing this package registers the built-in defenses."""

from redbench.defenses import guard_filter as _guard_filter  # noqa: F401  (registers "llama_guard_filter")
from redbench.defenses.base import BLOCK_MESSAGE, DEFENSES, Defense, Screening
from redbench.defenses.defended_target import DefendedTarget

__all__ = ["BLOCK_MESSAGE", "DEFENSES", "DefendedTarget", "Defense", "Screening"]
