"""Build every component an experiment needs from a validated config."""

from __future__ import annotations

from dataclasses import dataclass

from redbench.attacks.base import ATTACK_SOURCES, AttackSource
from redbench.cache import ResponseCache
from redbench.config import RedBenchConfig
from redbench.judges.base import JUDGES, Judge
from redbench.registry import BuildContext, load_builtin_components
from redbench.targets.base import TARGETS, Target


@dataclass
class Components:
    """The strategy objects selected by a config."""

    target: Target
    sources: list[AttackSource]
    judge: Judge

    def close(self) -> None:
        """Release resources held by components."""
        self.target.close()


def build_components(config: RedBenchConfig, cache: ResponseCache | None) -> Components:
    """Validate params and construct target, attack sources and judge.

    Does not contact any model backend, so it doubles as config validation.
    """
    load_builtin_components()
    context = BuildContext(seed=config.run.seed, cache=cache)
    target: Target = TARGETS.build(config.target, context)
    try:
        sources: list[AttackSource] = [ATTACK_SOURCES.build(spec, context) for spec in config.attacks]
        judge: Judge = JUDGES.build(config.judge, context)
    except Exception:
        target.close()
        raise
    return Components(target=target, sources=sources, judge=judge)
