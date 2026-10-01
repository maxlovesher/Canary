"""On-disk layout of one run: ``<output_dir>/<UTC timestamp>_<name>_<config hash>/``.

Files:
    config.resolved.yaml  validated config as run
    manifest.json         provenance: versions, model digest, dataset hashes, status
    results.jsonl         one ``AttackResult`` per line, flushed as the run progresses
    metrics.json          aggregate metrics
    run.log               full log of the run
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from redbench.errors import RedBenchError
from redbench.records import AttackResult


class ResultWriter:
    """Appends results to ``results.jsonl``, flushing each line so partial runs survive."""

    def __init__(self, handle: IO[str]) -> None:
        self._handle = handle
        self.count = 0

    def write(self, result: AttackResult) -> None:
        """Serialize and append one result."""
        self._handle.write(result.model_dump_json() + "\n")
        self._handle.flush()
        self.count += 1


class RunStore:
    """Owns one run directory."""

    CONFIG_FILE = "config.resolved.yaml"
    MANIFEST_FILE = "manifest.json"
    RESULTS_FILE = "results.jsonl"
    METRICS_FILE = "metrics.json"
    LOG_FILE = "run.log"

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(cls, output_dir: Path, name: str, config_hash: str, now: datetime | None = None) -> RunStore:
        """Create a fresh, uniquely named run directory."""
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        root = output_dir / f"{stamp}_{name}_{config_hash}"
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise RedBenchError(f"run directory {root} already exists; wait a second and retry") from None
        except OSError as exc:
            raise RedBenchError(f"cannot create run directory {root}: {exc}") from exc
        return cls(root)

    @property
    def run_id(self) -> str:
        """The run directory's name, used as the run's identifier."""
        return self.root.name

    def path(self, filename: str) -> Path:
        """Absolute path of a file inside the run directory."""
        return self.root / filename

    def write_text(self, filename: str, text: str) -> None:
        """Write a text file into the run directory."""
        self.path(filename).write_text(text, encoding="utf-8")

    def write_json(self, filename: str, data: dict[str, Any]) -> None:
        """Write pretty-printed JSON into the run directory."""
        self.write_text(filename, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    @contextmanager
    def result_writer(self) -> Iterator[ResultWriter]:
        """Open ``results.jsonl`` for appending results."""
        with self.path(self.RESULTS_FILE).open("a", encoding="utf-8") as handle:
            yield ResultWriter(handle)


def read_results(path: Path) -> list[AttackResult]:
    """Load every result from a ``results.jsonl`` file."""
    with path.open(encoding="utf-8") as handle:
        return [AttackResult.model_validate_json(line) for line in handle if line.strip()]
