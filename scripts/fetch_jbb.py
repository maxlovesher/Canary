"""Download the JailbreakBench JBB-Behaviors CSV and print its SHA-256.

The file lands in ``data/raw/`` (gitignored). Paste the printed hash into the
config's ``expected_sha256`` to pin the exact dataset version.

Usage:
    python scripts/fetch_jbb.py [--split harmful|benign] [--out-dir data/raw/jbb] [--force]

Source: https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors (MIT license).
Stdlib only, so it runs before ``uv sync``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/resolve/main/data"
FILES = {"harmful": "harmful-behaviors.csv", "benign": "benign-behaviors.csv"}


def fetch(url: str, dest: Path, timeout_s: float = 60.0) -> bytes:
    """Download ``url`` to ``dest`` atomically and return the bytes."""
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 (fixed https URL)
        data: bytes = response.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return data


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=sorted(FILES), default="harmful")
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw/jbb"))
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    args = parser.parse_args(argv)

    dest = args.out_dir / FILES[args.split]
    if dest.exists() and not args.force:
        data = dest.read_bytes()
        print(f"exists: {dest} (use --force to re-download)")
    else:
        url = f"{BASE_URL}/{FILES[args.split]}"
        try:
            data = fetch(url, dest)
        except (urllib.error.URLError, OSError) as exc:
            print(f"download failed from {url}: {exc}", file=sys.stderr)
            return 1
        print(f"downloaded {url} -> {dest} ({len(data)} bytes)")
    print(f"sha256: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
