"""Shared fixtures. All test data is synthetic placeholder text."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helpers import JBB_SAMPLE  # also registers the "scripted" test target


@pytest.fixture
def config_dict(tmp_path: Path) -> dict[str, Any]:
    """A valid config using the scripted target and the synthetic JBB sample."""
    return {
        "run": {
            "name": "test-run",
            "seed": 7,
            "output_dir": str(tmp_path / "runs"),
            "cache": {"mode": "off"},
        },
        "target": {"type": "scripted", "params": {}},
        "attacks": [{"type": "jailbreakbench", "params": {"path": str(JBB_SAMPLE)}}],
        "judge": {"type": "refusal_patterns", "params": {}},
    }


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Write a config dict to a YAML file and return its path."""

    def _write(data: dict[str, Any], name: str = "config.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return _write
