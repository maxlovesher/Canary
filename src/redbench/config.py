"""Top-level run configuration: models, YAML loading, ``--set`` overrides, hashing.

Component ``params`` are deliberately left as plain dicts here. Each component
validates its own params via its ``Params`` model when the factory builds it, so
adding a component never touches this module (see docs/DECISIONS.md, D2).
"""

import copy
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, PositiveInt, ValidationError

from redbench.errors import ConfigError

CacheMode = Literal["read_write", "read_only", "off"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentSpec(_Strict):
    """Selects a registered component by ``type`` and passes it ``params``."""

    type: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class CacheConfig(_Strict):
    """Response cache settings. ``read_only`` = strict replay: a miss is an error."""

    mode: CacheMode = "read_write"
    path: Path = Path(".cache/responses.sqlite")


class RunConfig(_Strict):
    """Run-level settings shared by every component."""

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=64)
    seed: int = 0
    output_dir: Path = Path("runs")
    max_cases: PositiveInt | None = None
    cache: CacheConfig = Field(default_factory=CacheConfig)


class PricingConfig(_Strict):
    """USD per million tokens, used for the cost metric. 0 for local models."""

    input_per_mtok: NonNegativeFloat = 0.0
    output_per_mtok: NonNegativeFloat = 0.0


class RedBenchConfig(_Strict):
    """A complete experiment definition."""

    run: RunConfig
    target: ComponentSpec
    attacks: list[ComponentSpec] = Field(min_length=1)
    judge: ComponentSpec
    pricing: PricingConfig = Field(default_factory=PricingConfig)


def apply_overrides(data: dict[str, Any], overrides: Sequence[str]) -> dict[str, Any]:
    """Return a copy of ``data`` with ``dotted.key=value`` overrides applied.

    Values are parsed as YAML (``10`` -> int, ``null`` -> None, ``[a, b]`` -> list).
    Integer path segments index into lists, e.g. ``attacks.0.params.sample=5``.
    """
    result = copy.deepcopy(data)
    for override in overrides:
        key, sep, raw_value = override.partition("=")
        if not sep or not key.strip():
            raise ConfigError(f"override must look like key.path=value, got {override!r}")
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"cannot parse value in override {override!r}: {exc}") from exc
        parts = key.strip().split(".")
        node: Any = result
        for part in parts[:-1]:
            node = _child(node, part, override)
        _assign(node, parts[-1], value, override)
    return result


def _child(node: Any, part: str, override: str) -> Any:
    if isinstance(node, list):
        return node[_list_index(node, part, override)]
    if isinstance(node, dict):
        return node.setdefault(part, {})
    raise ConfigError(f"override {override!r}: cannot descend into {part!r}")


def _assign(node: Any, part: str, value: Any, override: str) -> None:
    if isinstance(node, list):
        node[_list_index(node, part, override)] = value
    elif isinstance(node, dict):
        node[part] = value
    else:
        raise ConfigError(f"override {override!r}: cannot set {part!r}")


def _list_index(node: list[Any], part: str, override: str) -> int:
    if not part.isdigit() or int(part) >= len(node):
        raise ConfigError(f"override {override!r}: {part!r} is not a valid index (list has {len(node)} items)")
    return int(part)


def load_config(path: Path, overrides: Sequence[str] = ()) -> RedBenchConfig:
    """Load, override, and validate a YAML config file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config {path} must be a YAML mapping at the top level")
    data = apply_overrides(data, overrides)
    try:
        return RedBenchConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc


def config_hash(config: RedBenchConfig) -> str:
    """Short, key-order-independent fingerprint of a config (12 hex chars)."""
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def dump_config(config: RedBenchConfig) -> str:
    """Serialize a validated config back to YAML (written as ``config.resolved.yaml``)."""
    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
