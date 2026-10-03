import json

from redbench.cli import EXIT_ERROR, EXIT_OK, main
from redbench.labeling import format_result, pending_results, run_labeling
from redbench.labels import LabelStore
from redbench.records import AttackResult, TargetResponse, Verdict
from tests.helpers import make_case


def make_result(case_id: str, text: str = "placeholder answer", error: bool = False) -> AttackResult:
    if error:
        return AttackResult(
            case=make_case(case_id),
            response=None,
            error="boom",
            verdict=Verdict(success=None, judge="rule", reason="target error"),
        )
    return AttackResult(
        case=make_case(case_id, prompt=f"placeholder request {case_id}"),
        response=TargetResponse(text=text, model="m", latency_ms=1, reasoning="placeholder reasoning"),
        verdict=Verdict(success=True, judge="rule", reason="JUDGE-REASON-MARKER"),
    )


def scripted(*answers: str):
    """input() replacement that replays answers, then signals end of input."""
    queue = list(answers)

    def _input(_prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return _input


def run(results, store, *answers, **kwargs):
    printed: list[str] = []
    summary = run_labeling(results, store, input_fn=scripted(*answers), print_fn=printed.append, **kwargs)
    return summary, "\n".join(printed)


def test_labels_each_case_and_saves_immediately(tmp_path):
    store = LabelStore.for_run(tmp_path)
    results = [make_result("c1"), make_result("c2"), make_result("c3")]
    summary, _ = run(results, store, "r", "s", "h", labeler="tester")
    assert (summary.labeled, summary.skipped, summary.remaining, summary.quit_early) == (3, 0, 0, False)
    labels = store.load()
    assert [labels[c].label for c in ("c1", "c2", "c3")] == ["refusal", "safe_compliance", "harmful_compliance"]
    assert labels["c1"].labeler == "tester"


def test_notes_skip_help_and_quit(tmp_path):
    store = LabelStore.for_run(tmp_path)
    results = [make_result("c1"), make_result("c2"), make_result("c3")]
    summary, output = run(results, store, "?", "x", "n", "borderline", "s", "k", "q")
    assert (summary.labeled, summary.skipped, summary.remaining, summary.quit_early) == (1, 1, 1, True)
    assert store.load()["c1"].notes == "borderline"
    assert "harmful_compliance  meaningfully helps" in output  # rubric shown on "?"
    assert "[r] refusal" in output  # help shown on unknown key


def test_resume_skips_labeled_and_relabel_revisits(tmp_path):
    store = LabelStore.for_run(tmp_path)
    results = [make_result("c1"), make_result("c2")]
    run(results, store, "r")  # label c1, then end of input
    summary, _ = run(results, store, "s")
    assert summary.labeled == 1 and set(store.load()) == {"c1", "c2"}
    summary, _ = run(results, store, "h", "h", relabel=True)
    assert summary.labeled == 2
    assert {label.label for label in store.load().values()} == {"harmful_compliance"}


def test_stale_label_is_asked_again(tmp_path):
    store = LabelStore.for_run(tmp_path)
    run([make_result("c1", text="old placeholder")], store, "r")
    assert pending_results([make_result("c1", text="new placeholder")], store.load()) != []


def test_target_errors_are_not_labeled(tmp_path):
    store = LabelStore.for_run(tmp_path)
    summary, _ = run([make_result("c1", error=True)], store)
    assert summary.labeled == 0 and summary.remaining == 0


def test_display_is_blind_to_the_judge():
    text = format_result(make_result("c1"), 1, 1)
    assert "placeholder request c1" in text and "placeholder answer" in text
    assert "JUDGE-REASON-MARKER" not in text and "rule" not in text
    assert "placeholder reasoning" not in text
    assert "placeholder reasoning" in format_result(make_result("c1"), 1, 1, show_reasoning=True)


def test_cli_label_then_agreement(config_dict, write_config, tmp_path, monkeypatch, capsys):
    config_dict["target"]["params"] = {"replies": {"jbb-1": "I cannot help with that."}}
    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    run_dir = next((tmp_path / "runs").iterdir())

    assert main(["agreement", str(run_dir)]) == EXIT_ERROR  # no labels yet

    # Label all 6 synthetic cases: jbb-1 refusal, the rest harmless compliance.
    monkeypatch.setattr("builtins.input", scripted("r", "s", "s", "s", "s", "s"))
    assert main(["label", str(run_dir), "--labeler", "tester"]) == EXIT_OK
    assert len(LabelStore.for_run(run_dir).load()) == 6

    capsys.readouterr()
    assert main(["agreement", str(run_dir)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "judge refusal_patterns" in out
    report = json.loads((run_dir / "agreement.json").read_text(encoding="utf-8"))
    rule = report["judges"]["refusal_patterns"]
    # The refusal judge matches "did it refuse?" perfectly here...
    assert rule["vs_any_compliance"]["accuracy"] == 1.0
    # ...but flags 5 harmless answers as attack successes against the harmfulness truth.
    assert rule["vs_harmful_compliance"]["confusion"] == {"tp": 0, "fp": 5, "fn": 0, "tn": 1}


def test_cli_agreement_with_labels_from_another_run(config_dict, write_config, tmp_path, monkeypatch):
    config_path = write_config(config_dict)
    assert main(["run", str(config_path)]) == EXIT_OK
    first = next((tmp_path / "runs").iterdir())
    monkeypatch.setattr("builtins.input", scripted("s", "s", "s", "s", "s", "s"))
    assert main(["label", str(first)]) == EXIT_OK

    assert main(["run", str(config_path), "--set", "run.name=rejudge"]) == EXIT_OK
    second = next(p for p in (tmp_path / "runs").iterdir() if "rejudge" in p.name)
    assert main(["agreement", str(second), "--labels", str(first / "labels.jsonl")]) == EXIT_OK
    report = json.loads((second / "agreement.json").read_text(encoding="utf-8"))
    assert report["n_matched"] == 6  # identical responses: hashes match across runs


def test_cli_label_rejects_non_run_dir(tmp_path):
    assert main(["label", str(tmp_path)]) == EXIT_ERROR
