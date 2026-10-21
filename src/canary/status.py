"""Run status at a glance (``canary status``): progress, and runs that silently died.

Reads only ``manifest.json`` and the *line count* of ``results.jsonl``; never
response content. A run still marked ``running`` whose files have not changed for
``stale_after_s`` seconds is reported as ``stale`` (killed process, sleep, crash).
Its cached responses are not lost: re-running the same config replays them.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from canary.run_store import RunStore


@dataclass(frozen=True)
class RunStatus:
    """One run directory's state."""

    run_id: str
    status: str  # completed | interrupted | running | stale | unknown
    done: int
    total: int | None
    started_at: str
    idle_s: float  # seconds since the run's files last changed


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def scan_runs(runs_dir: Path, *, stale_after_s: float = 900, now: float | None = None) -> list[RunStatus]:
    """Status of every run directory, newest first."""
    now = time.time() if now is None else now
    statuses = []
    for path in runs_dir.iterdir() if runs_dir.is_dir() else []:
        manifest_path = path / RunStore.MANIFEST_FILE
        if not path.is_dir() or path.name.startswith("_"):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        results_path = path / RunStore.RESULTS_FILE
        touched = [p.stat().st_mtime for p in (manifest_path, results_path) if p.is_file()]
        idle_s = now - max(touched) if touched else float("inf")
        status = str(manifest.get("status", "unknown"))
        if status == "running" and idle_s > stale_after_s:
            status = "stale"
        statuses.append(
            RunStatus(
                run_id=path.name,
                status=status,
                done=_count_lines(results_path),
                total=manifest.get("n_cases"),
                started_at=str(manifest.get("started_at", "")),
                idle_s=idle_s,
            )
        )
    return sorted(statuses, key=lambda s: s.run_id, reverse=True)


def format_status(statuses: list[RunStatus], *, limit: int | None = None) -> str:
    """Terminal table; active and stale runs are always shown, others up to ``limit``."""
    shown = [s for s in statuses if s.status in ("running", "stale")]
    rest = [s for s in statuses if s not in shown]
    shown += rest if limit is None else rest[: max(0, limit - len(shown))]
    lines = [f"{'run':<58} {'status':<11} {'progress':>9}  idle"]
    for s in sorted(shown, key=lambda s: s.run_id, reverse=True):
        progress = f"{s.done}/{s.total}" if s.total is not None else str(s.done)
        lines.append(f"{s.run_id[:58]:<58} {s.status:<11} {progress:>9}  {_idle(s.idle_s)}")
    hidden = len(statuses) - len(shown)
    if hidden > 0:
        lines.append(f"... {hidden} older runs hidden (use --all)")
    if any(s.status == "stale" for s in shown):
        lines.append("stale = marked running but untouched; re-running its config replays cached responses.")
    return "\n".join(lines)


def _idle(seconds: float) -> str:
    if seconds == float("inf"):
        return "?"
    if seconds < 120:
        return f"{seconds:.0f}s"
    if seconds < 7200:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}h"
    return f"{seconds / 86400:.0f}d"
