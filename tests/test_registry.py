import pytest
from pydantic import BaseModel

from redbench.attacks.base import ATTACK_SOURCES
from redbench.config import ComponentSpec
from redbench.errors import ComponentError
from redbench.judges.base import JUDGES
from redbench.registry import BuildContext, Registry
from redbench.targets.base import TARGETS


class _Thing:
    class Params(BaseModel):
        size: int = 1

    def __init__(self, params, context):
        self.params = params
        self.context = context


def test_builtins_registered():
    assert "ollama_chat" in TARGETS.names()
    assert "jailbreakbench" in ATTACK_SOURCES.names()
    assert "refusal_patterns" in JUDGES.names()


def test_build_validates_params_and_passes_context():
    registry: Registry[_Thing] = Registry("thing")
    registry.register("thing")(_Thing)
    context = BuildContext(seed=3)
    built = registry.build(ComponentSpec(type="thing", params={"size": 4}), context)
    assert built.params.size == 4
    assert built.context is context


def test_invalid_params_raise_component_error():
    registry: Registry[_Thing] = Registry("thing")
    registry.register("thing")(_Thing)
    with pytest.raises(ComponentError, match="invalid params for thing 'thing'"):
        registry.build(ComponentSpec(type="thing", params={"size": "big"}), BuildContext(seed=0))


def test_unknown_type_lists_available():
    registry: Registry[_Thing] = Registry("thing")
    registry.register("alpha")(_Thing)
    with pytest.raises(ComponentError, match="available: alpha"):
        registry.get("beta")


def test_duplicate_registration_rejected():
    registry: Registry[_Thing] = Registry("thing")
    registry.register("alpha")(_Thing)
    with pytest.raises(ComponentError, match="already registered"):
        registry.register("alpha")(_Thing)


def test_class_without_params_model_rejected():
    registry: Registry[object] = Registry("thing")

    class NoParams:
        pass

    with pytest.raises(ComponentError, match="Params"):
        registry.register("bad")(NoParams)


def test_ollama_target_params_validated_at_build():
    with pytest.raises(ComponentError):
        TARGETS.build(ComponentSpec(type="ollama_chat", params={"model": "m", "temperature": 5}), BuildContext(seed=0))
