"""The attack loop: cases -> target -> judge -> recorded result.

The runner knows nothing about configs or files beyond the ``ResultWriter`` it is
handed; ``redbench.experiment`` wires it to config, cache, and run directory.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from redbench.attacks.base import AttackSource
from redbench.errors import DatasetError, TargetError
from redbench.judges.base import Judge
from redbench.records import AttackCase, AttackResult, Verdict
from redbench.run_store import ResultWriter
from redbench.targets.base import Target

logger = logging.getLogger(__name__)


@dataclass
class RunOutcome:
    """Results of one pass over the cases."""

    results: list[AttackResult] = field(default_factory=list)
    interrupted: bool = False


class Runner:
    """Sends every attack case to the target and judges the response.

    Target failures (``TargetError``) are recorded as unjudged results
    (``verdict.success is None``) and the run continues; any other exception
    is a bug and propagates.
    """

    def __init__(
        self,
        target: Target,
        sources: Sequence[AttackSource],
        judge: Judge,
        *,
        max_cases: int | None = None,
        progress_every: int = 10,
    ) -> None:
        self.target = target
        self.sources = list(sources)
        self.judge = judge
        self.max_cases = max_cases
        self.progress_every = max(1, progress_every)

    def load_cases(self) -> list[AttackCase]:
        """Load cases from every source, reject duplicate IDs, apply ``max_cases``."""
        cases: list[AttackCase] = []
        for source in self.sources:
            loaded = source.load()
            logger.info("loaded %d cases from %s", len(loaded), source.name)
            cases.extend(loaded)
        seen: set[str] = set()
        for case in cases:
            if case.id in seen:
                raise DatasetError(f"duplicate attack case id {case.id!r} across attack sources")
            seen.add(case.id)
        if self.max_cases is not None and len(cases) > self.max_cases:
            logger.info("truncating %d cases to max_cases=%d", len(cases), self.max_cases)
            cases = cases[: self.max_cases]
        return cases

    def run_case(self, case: AttackCase) -> AttackResult:
        """Attack the target with one case and judge the outcome."""
        try:
            response = self.target.generate(case)
        except TargetError as exc:
            logger.warning("target error on case %s: %s", case.id, exc)
            verdict = Verdict(success=None, judge=self.judge.name, reason="target error; not judged")
            return AttackResult(case=case, response=None, error=str(exc), verdict=verdict)
        verdict = self.judge.judge(case, response)
        return AttackResult(case=case, response=response, verdict=verdict)

    def run(self, cases: Sequence[AttackCase], writer: ResultWriter) -> RunOutcome:
        """Run every case, streaming results to ``writer``. Ctrl-C stops cleanly."""
        outcome = RunOutcome()
        total = len(cases)
        try:
            for index, case in enumerate(cases, start=1):
                result = self.run_case(case)
                writer.write(result)
                outcome.results.append(result)
                if index % self.progress_every == 0 or index == total:
                    logger.info("progress %d/%d", index, total)
        except KeyboardInterrupt:
            outcome.interrupted = True
            logger.warning("interrupted after %d/%d cases; partial results kept", len(outcome.results), total)
        return outcome
