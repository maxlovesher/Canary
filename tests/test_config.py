from pathlib import Path

import pytest

from redbench.config import apply_overrides, config_hash, load_config
from redbench.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loads_valid_config(config_dict, write_config):
    config = load_config(write_config(config_dict))
    assert config.run.name == "test-run"
    assert config.run.cache.mode == "off"
    assert config.attacks[0].type == "jailbreakbench"
    assert config.pricing.input_per_mtok == 0.0


def test_shipped_m1_config_is_valid():
    config = load_config(REPO_ROOT / "configs" / "m1_jbb_direct.yaml")
    assert config.target.type == "ollama_chat"
    assert config.judge.type == "refusal_patterns"


def test_shipped_m5_config_reuses_m1_target_for_cache_hits():
    m1 = load_config(REPO_ROOT / "configs" / "m1_jbb_direct.yaml")
    m5 = load_config(REPO_ROOT / "configs" / "m5_judge_validation.yaml")
    assert m5.target == m1.target and m5.attacks == m1.attacks and m5.run.seed == m1.run.seed
    assert [j.type for j in m5.secondary_judges] == ["ollama_llm_judge", "ollama_llm_judge"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(unexpected_key=1),
        lambda d: d["run"].update(nmae="typo"),
        lambda d: d.update(attacks=[]),
        lambda d: d["run"].update(name="bad name!"),
        lambda d: d["run"].update(max_cases=0),
        lambda d: d.pop("judge"),
        lambda d: d["run"]["cache"].update(mode="sometimes"),
    ],
)
def test_rejects_invalid_config(config_dict, write_config, mutate):
    mutate(config_dict)
    with pytest.raises(ConfigError):
        load_config(write_config(config_dict))


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_non_mapping_yaml_rejected(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_overrides_parse_yaml_values_and_index_lists(config_dict, write_config):
    config = load_config(
        write_config(config_dict),
        ["run.seed=99", "run.max_cases=3", "attacks.0.params.sample=2", "target.params.default_reply=hi"],
    )
    assert config.run.seed == 99
    assert config.run.max_cases == 3
    assert config.attacks[0].params["sample"] == 2
    assert config.target.params["default_reply"] == "hi"


def test_override_does_not_mutate_input():
    data = {"a": {"b": 1}}
    result = apply_overrides(data, ["a.b=2"])
    assert data == {"a": {"b": 1}}
    assert result == {"a": {"b": 2}}


@pytest.mark.parametrize("override", ["no_equals_sign", "=value", "attacks.5.params.x=1", "attacks.x.params=1"])
def test_bad_overrides_rejected(config_dict, write_config, override):
    with pytest.raises(ConfigError):
        load_config(write_config(config_dict), [override])


def test_config_hash_is_stable_and_sensitive(config_dict, write_config):
    path = write_config(config_dict)
    assert config_hash(load_config(path)) == config_hash(load_config(path))
    assert config_hash(load_config(path)) != config_hash(load_config(path, ["run.seed=8"]))
    assert len(config_hash(load_config(path))) == 12
