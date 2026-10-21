"""The attack loop: cases -> target -> judge -> recorded result.

The runner knows nothing about configs or files beyond the ``ResultWriter`` it is
handed; ``canary.experiment`` wires it to config, cache, and run directory.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from canary.attacks.base import AttackSource
from canary.errors import DatasetError, TargetError
from canary.judges.base import Judge
from canary.records import AttackCase, AttackResult, Verdict
from canary.run_store import ResultWriter
from canary.targets.base import Target

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
        secondary_judges: Sequence[Judge] = (),
        max_cases: int | None = None,
        progress_every: int = 10,
        concurrency: int = 1,
    ) -> None:
        self.target = target
        self.sources = list(sources)
        self.judge = judge
        self.secondary_judges = list(secondary_judges)
        self.max_cases = max_cases
        self.progress_every = max(1, progress_every)
        self.concurrency = max(1, concurrency)

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
            unjudged = [
                Verdict(success=None, judge=judge.name, reason="target error; not judged")
                for judge in (self.judge, *self.secondary_judges)
            ]
            return AttackResult(
                case=case, response=None, error=str(exc), verdict=unjudged[0], secondary_verdicts=unjudged[1:]
            )
        return AttackResult(
            case=case,
            response=response,
            verdict=self.judge.judge(case, response),
            secondary_verdicts=[judge.judge(case, response) for judge in self.secondary_judges],
        )

    def run(self, cases: Sequence[AttackCase], writer: ResultWriter) -> RunOutcome:
        """Run every case, streaming results to ``writer`` in case order. Ctrl-C stops cleanly.

        With ``concurrency > 1`` cases are processed by a thread pool (the backend
        serves several requests at once), but results are still written in case order,
        so ``results.jsonl`` looks the same as a sequential run.
        """
        outcome = RunOutcome()
        total = len(cases)
        pool = ThreadPoolExecutor(max_workers=self.concurrency) if self.concurrency > 1 else None
        try:
            if pool is None:
                results: Iterator[AttackResult] = (self.run_case(case) for case in cases)
            else:
                results = (future.result() for future in [pool.submit(self.run_case, case) for case in cases])
            for index, result in enumerate(results, start=1):
                writer.write(result)
                outcome.results.append(result)
                if index % self.progress_every == 0 or index == total:
                    logger.info("progress %d/%d", index, total)
        except KeyboardInterrupt:
            outcome.interrupted = True
            logger.warning("interrupted after %d/%d cases; partial results kept", len(outcome.results), total)
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
        return outcome
