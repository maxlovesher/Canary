"""JailbreakBench JBB-Behaviors loader.

Milestone 1 uses the *direct-request* baseline: each case's prompt is the
behavior's ``Goal`` text, sent unmodified. Attack transforms (milestone 3) build
on top of these cases.

Expected CSV columns: ``Index, Goal, Target, Behavior, Category, Source``
(``Goal``, ``Behavior`` and ``Category`` are required).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from redbench.attacks.base import ATTACK_SOURCES
from redbench.attacks.selection import select_cases
from redbench.errors import DatasetError
from redbench.records import AttackCase
from redbench.registry import BuildContext

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("Goal", "Behavior", "Category")


@ATTACK_SOURCES.register("jailbreakbench")
class JailbreakBenchSource:
    """Loads JBB-Behaviors rows as attack cases, optionally filtered and sampled."""

    class Params(BaseModel):
        model_config = ConfigDict(extra="forbid")

        path: Path
        expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
        categories: list[str] | None = Field(default=None, min_length=1)
        sample: PositiveInt | None = None  # sample this many cases using run.seed

    name = "jailbreakbench"

    def __init__(self, params: Params, context: BuildContext) -> None:
        self.params = params
        self._seed = context.seed
        self._sha256: str | None = None
        self._n_loaded: int | None = None

    def load(self) -> list[AttackCase]:
        """Read, verify, filter, and sample the dataset."""
        raw = self._read_bytes()
        self._sha256 = hashlib.sha256(raw).hexdigest()
        if self.params.expected_sha256 and self._sha256 != self.params.expected_sha256:
            raise DatasetError(
                f"{self.params.path} sha256 is {self._sha256}, expected {self.params.expected_sha256}; "
                "the dataset changed or the wrong file is configured"
            )
        cases = select_cases(
            self._parse(raw), categories=self.params.categories, sample=self.params.sample, seed=self._seed
        )
        self._n_loaded = len(cases)
        logger.info("jailbreakbench: %d cases from %s (sha256 %s)", len(cases), self.params.path, self._sha256[:12])
        return cases

    def describe(self) -> dict[str, Any]:
        """Path, content hash and filters, for the run manifest."""
        return {
            "type": self.name,
            **self.params.model_dump(mode="json"),
            "sha256": self._sha256,
            "n_cases": self._n_loaded,
        }

    # -- internals ----------------------------------------------------------

    def _read_bytes(self) -> bytes:
        path = self.params.path
        if not path.is_file():
            raise DatasetError(f"JailbreakBench file not found: {path} (see scripts/fetch_jbb.py)")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise DatasetError(f"cannot read {path}: {exc}") from exc

    def _parse(self, raw: bytes) -> list[AttackCase]:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DatasetError(f"{self.params.path} is not UTF-8: {exc}") from exc
        reader = csv.DictReader(io.StringIO(text))
        missing = [col for col in REQUIRED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise DatasetError(f"{self.params.path} is missing required columns: {', '.join(missing)}")
        cases = [self._to_case(row_number, row) for row_number, row in enumerate(reader, start=1)]
        if not cases:
            raise DatasetError(f"{self.params.path} contains no rows")
        return cases

    def _to_case(self, row_number: int, row: dict[str, str | None]) -> AttackCase:
        goal = (row.get("Goal") or "").strip()
        category = (row.get("Category") or "").strip()
        if not goal or not category:
            raise DatasetError(f"{self.params.path} row {row_number}: Goal and Category must be non-empty")
        index = (row.get("Index") or "").strip() or str(row_number)
        return AttackCase(
            id=f"jbb-{index}",
            source=self.name,
            category=category,
            prompt=goal,
            metadata={
                "row": row_number,
                "behavior": (row.get("Behavior") or "").strip(),
                "jbb_source": (row.get("Source") or "").strip(),
            },
        )
