"""Secondary judges: extra verdicts per result, reported as separate ASR columns."""

import json

import pytest

from redbench.cli import EXIT_ERROR, EXIT_OK, main
from redbench.config import PricingConfig
from redbench.metrics import compute_metrics
from redbench.records import AttackResult, TargetResponse, Verdict
from redbench.run_store import RunStore
from tests.helpers import make_case


def test_secondary_asr_uses_named_verdicts():
    response = TargetResponse(text="t", model="m", latency_ms=1)
    results = [
        AttackResult(
            case=make_case("c1"),
            response=response,
            verdict=Verdict(success=False, judge="primary", reason="r"),
            secondary_verdicts=[Verdict(success=True, judge="extra", reason="r")],
        ),
        AttackResult(
            case=make_case("c2"),
            response=response,
            verdict=Verdict(success=True, judge="primary", reason="r"),
        ),  # "extra" did not run here: unjudged for that column
    ]
    metrics = compute_metrics(
        results, success_definition="d", pricing=PricingConfig(), secondary_definitions={"extra": "e"}
    )
    assert metrics["asr"]["overall"]["rate"] == pytest.approx(0.5)
    extra = metrics["secondary_asr"]["extra"]
    assert extra["success_definition"] == "e"
    assert extra["asr"]["overall"]["n"] == 1 and extra["asr"]["overall"]["rate"] == 1.0
    assert extra["asr"]["n_unjudged"] == 1


def test_secondary_judges_run_end_to_end(config_dict, write_config, tmp_path):
    config_dict["judge"] = {"type": "refusal_patterns", "params": {"window_chars": 50}}
    config_dict["secondary_judges"] = []
    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    run_dir = next((tmp_path / "runs").iterdir())
    metrics = json.loads((run_dir / RunStore.METRICS_FILE).read_text(encoding="utf-8"))
    assert metrics["secondary_asr"] == {}


def test_duplicate_judge_types_rejected(config_dict, write_config):
    config_dict["secondary_judges"] = [{"type": "refusal_patterns"}]
    assert main(["validate", str(write_config(config_dict))]) == EXIT_ERROR
