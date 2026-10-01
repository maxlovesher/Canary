"""End-to-end: CLI -> config -> factory -> runner -> run directory, with the scripted target."""

import json
from pathlib import Path

from redbench.cli import EXIT_ERROR, EXIT_INTERRUPTED, EXIT_OK, main
from redbench.run_store import RunStore, read_results


def only_run_dir(output_dir: Path) -> Path:
    dirs = list(output_dir.iterdir())
    assert len(dirs) == 1
    return dirs[0]


def test_run_writes_complete_run_directory(config_dict, write_config, tmp_path, capsys):
    config_dict["target"]["params"] = {"replies": {"jbb-1": "I cannot help with that."}, "fail_ids": ["jbb-6"]}
    code = main(["run", str(write_config(config_dict))])
    assert code == EXIT_OK

    run_dir = only_run_dir(tmp_path / "runs")
    assert "_test-run_" in run_dir.name
    for filename in (
        RunStore.CONFIG_FILE,
        RunStore.MANIFEST_FILE,
        RunStore.RESULTS_FILE,
        RunStore.METRICS_FILE,
        RunStore.LOG_FILE,
    ):
        assert (run_dir / filename).is_file(), filename

    results = read_results(run_dir / RunStore.RESULTS_FILE)
    assert len(results) == 6

    metrics = json.loads((run_dir / RunStore.METRICS_FILE).read_text(encoding="utf-8"))
    assert metrics["provenance"] == "measured"
    assert metrics["success_definition"] == "proxy_non_refusal"
    assert metrics["asr"]["overall"] == {
        "successes": 4,
        "n": 5,
        "rate": 0.8,
        "ci95_low": metrics["asr"]["overall"]["ci95_low"],
        "ci95_high": metrics["asr"]["overall"]["ci95_high"],
    }
    assert metrics["asr"]["n_unjudged"] == 1

    manifest = json.loads((run_dir / RunStore.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["n_cases"] == 6 and manifest["n_results"] == 6
    assert manifest["attack_sources"][0]["sha256"]
    assert manifest["judge"]["success_definition"] == "proxy_non_refusal"

    out = capsys.readouterr().out
    assert "OVERALL" in out and "proxy_non_refusal" in out


def test_overrides_apply_from_cli(config_dict, write_config, tmp_path):
    assert main(["run", str(write_config(config_dict)), "--set", "run.max_cases=2"]) == EXIT_OK
    results = read_results(only_run_dir(tmp_path / "runs") / RunStore.RESULTS_FILE)
    assert len(results) == 2


def test_interrupted_run_marks_manifest(config_dict, write_config, tmp_path):
    config_dict["target"]["params"] = {"interrupt_ids": ["jbb-3"]}
    assert main(["run", str(write_config(config_dict))]) == EXIT_INTERRUPTED
    run_dir = only_run_dir(tmp_path / "runs")
    manifest = json.loads((run_dir / RunStore.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["status"] == "interrupted" and manifest["n_results"] == 2


def test_validate_does_not_create_run_dir(config_dict, write_config, tmp_path, capsys):
    assert main(["validate", str(write_config(config_dict))]) == EXIT_OK
    assert "6 cases across 3 categories" in capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


def test_invalid_config_exits_with_error(config_dict, write_config):
    config_dict["judge"]["type"] = "no_such_judge"
    assert main(["validate", str(write_config(config_dict))]) == EXIT_ERROR


def test_missing_dataset_exits_with_error(config_dict, write_config, tmp_path):
    config_dict["attacks"][0]["params"]["path"] = str(tmp_path / "missing.csv")
    assert main(["validate", str(write_config(config_dict))]) == EXIT_ERROR
