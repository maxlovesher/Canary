"""Attack sources. Importing this package registers the built-in sources."""

from redbench.attacks import jailbreakbench as _jailbreakbench  # noqa: F401  (registers "jailbreakbench")
from redbench.attacks.base import ATTACK_SOURCES, AttackSource

__all__ = ["ATTACK_SOURCES", "AttackSource"]
