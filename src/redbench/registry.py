"""Component registries: map a config ``type`` string to a component class.

Every component class declares a nested pydantic ``Params`` model and a
constructor ``__init__(self, params, context)``. ``Registry.build`` validates a
spec's raw ``params`` against that model before constructing the component, so
all config errors surface at startup, before any model call.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from redbench.errors import ComponentError
from redbench.scenario import make_canary

if TYPE_CHECKING:
    from redbench.cache import ResponseCache
    from redbench.config import ComponentSpec

T = TypeVar("T")

# Packages whose __init__ imports (and thereby registers) the built-in components.
_BUILTIN_PACKAGES = ("redbench.targets", "redbench.attacks", "redbench.judges")


@dataclass(frozen=True)
class BuildContext:
    """Run-level dependencies handed to every component at construction time."""

    seed: int
    cache: ResponseCache | None = None

    @property
    def canary(self) -> str:
        """The run's canary secret: planted by agent targets, searched for by judges."""
        return make_canary(self.seed)


class Registry(Generic[T]):
    """Name -> class mapping for one kind of component (target, attack source, judge)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._classes: dict[str, type[Any]] = {}

    def register(self, name: str) -> Callable[[type[Any]], type[Any]]:
        """Class decorator registering a component under ``name``."""

        def decorator(cls: type[Any]) -> type[Any]:
            if name in self._classes:
                raise ComponentError(f"{self.kind} type {name!r} is already registered")
            params_model = getattr(cls, "Params", None)
            if not (isinstance(params_model, type) and issubclass(params_model, BaseModel)):
                raise ComponentError(f"{self.kind} {cls.__name__} must define a pydantic 'Params' model")
            self._classes[name] = cls
            return cls

        return decorator

    def names(self) -> list[str]:
        """Registered type names, sorted."""
        return sorted(self._classes)

    def get(self, name: str) -> type[Any]:
        """Look up a registered class, listing the alternatives on failure."""
        try:
            return self._classes[name]
        except KeyError:
            available = ", ".join(self.names()) or "<none>"
            raise ComponentError(f"unknown {self.kind} type {name!r}; available: {available}") from None

    def build(self, spec: ComponentSpec, context: BuildContext) -> T:
        """Validate ``spec.params`` and construct the component."""
        cls = self.get(spec.type)
        try:
            params = cls.Params.model_validate(spec.params)
        except ValidationError as exc:
            raise ComponentError(f"invalid params for {self.kind} {spec.type!r}:\n{exc}") from exc
        component: T = cls(params, context)
        return component


def load_builtin_components() -> None:
    """Import the built-in component packages so their classes self-register."""
    for package in _BUILTIN_PACKAGES:
        importlib.import_module(package)
