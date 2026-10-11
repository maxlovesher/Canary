"""Defenses. Importing this package registers the built-in defenses."""

from canary.defenses import guard_filter as _guard_filter  # noqa: F401  (registers "llama_guard_filter")
from canary.defenses.base import BLOCK_MESSAGE, DEFENSES, Defense, Screening
from canary.defenses.defended_target import DefendedTarget

__all__ = ["BLOCK_MESSAGE", "DEFENSES", "DefendedTarget", "Defense", "Screening"]
