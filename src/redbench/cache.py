"""SQLite-backed response cache: makes runs cheap to repeat and exactly replayable.

Keys are SHA-256 hashes of everything that can change a response (target type,
model digest, full request body including seed and sampling params). Values are
the JSON-serialized ``TargetResponse`` fields.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from redbench.config import CacheConfig
from redbench.errors import RedBenchError

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def make_cache_key(parts: dict[str, Any]) -> str:
    """Hash a JSON-serializable dict independent of key order."""
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache:
    """Key -> JSON payload store in a single SQLite file.

    Args:
        path: SQLite file location; parent directories are created in read-write mode.
        read_only: strict replay. ``put`` becomes a no-op and the file must already exist.
    """

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        try:
            if read_only:
                if not path.is_file():
                    raise RedBenchError(f"cache mode is read_only but cache file {path} does not exist")
                self._conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(path)
                self._conn.execute(_SCHEMA)
                self._conn.commit()
        except sqlite3.Error as exc:
            raise RedBenchError(f"cannot open response cache {path}: {exc}") from exc
        logger.debug("opened response cache %s (read_only=%s)", path, read_only)

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached payload for ``key``, or None on a miss."""
        row = self._conn.execute("SELECT payload FROM responses WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, key: str, payload: dict[str, Any]) -> None:
        """Store ``payload`` under ``key`` (ignored in read-only mode)."""
        if self.read_only:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def __len__(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> ResponseCache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


@contextmanager
def open_cache(config: CacheConfig) -> Iterator[ResponseCache | None]:
    """Yield a cache for ``config``, or None when caching is off."""
    if config.mode == "off":
        yield None
        return
    with ResponseCache(config.path, read_only=config.mode == "read_only") as cache:
        yield cache
