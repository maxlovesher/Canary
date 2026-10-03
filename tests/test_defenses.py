"""Defenses: the target wrapper, the Llama Guard filter, parsing, and config wiring."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from redbench.cli import EXIT_OK, main
from redbench.defenses import BLOCK_MESSAGE, DefendedTarget, Screening
from redbench.defenses.guard_filter import LlamaGuardFilter
from redbench.judges.refusal_patterns import RefusalPatternJudge
from redbench.llama_guard import guard_messages, parse_guard_output
from redbench.records import AttackCase, TargetResponse
from redbench.registry import BuildContext
from redbench.run_store import RunStore, read_results
from tests.helpers import ScriptedTarget, make_case

CTX = BuildContext(seed=0)


class FakeDefense:
    def __init__(self, stage: str, block_ids: set[str], latency_ms: float = 5.0) -> None:
        self.stage = stage
        self.name = f"fake_{stage}"
        self.block_ids = block_ids
        self.latency_ms = latency_ms
        self.seen: list[tuple[str, str | None]] = []
        self.closed = False

    def screen(self, case: AttackCase, response: TargetResponse | None) -> Screening:
        self.seen.append((case.id, None if response is None else response.text))
        return Screening(blocked=case.id in self.block_ids, reason="flagged", latency_ms=self.latency_ms)

    def describe(self) -> dict[str, Any]:
        return {"type": self.name}

    def close(self) -> None:
        self.closed = True


def test_input_block_skips_the_target():
    target = ScriptedTarget(ScriptedTarget.Params(), CTX)
    defended = DefendedTarget(target, [FakeDefense("input", {"c1"})])
    response = defended.generate(make_case("c1"))
    assert response.text == BLOCK_MESSAGE
    assert response.blocked_by == "fake_input: flagged"
    assert response.finish_reason == "blocked" and response.latency_ms == 5.0
    assert target.calls == []


def test_output_block_replaces_answer_and_sees_it():
    target = ScriptedTarget(ScriptedTarget.Params(default_reply="placeholder answer"), CTX)
    output = FakeDefense("output", {"c1"})
    defended = DefendedTarget(target, [output])
    response = defended.generate(make_case("c1"))
    assert response.text == BLOCK_MESSAGE and response.blocked_by.startswith("fake_output")
    assert output.seen == [("c1", "placeholder answer")]
    assert response.latency_ms == 10.0 + 5.0  # target + defense
    assert target.calls == ["c1"]


def test_allowed_requests_pass_through_with_overhead():
    target = ScriptedTarget(ScriptedTarget.Params(default_reply="placeholder answer"), CTX)
    defended = DefendedTarget(target, [FakeDefense("input", set()), FakeDefense("output", set())])
    response = defended.generate(make_case("c2"))
    assert response.text == "placeholder answer" and response.blocked_by is None
    assert response.latency_ms == 10.0 + 5.0 + 5.0


def test_blocked_answer_counts_as_refusal_for_the_judge():
    judge = RefusalPatternJudge(RefusalPatternJudge.Params(), CTX)
    blocked = TargetResponse(text=BLOCK_MESSAGE, model="defense", latency_ms=1, blocked_by="x")
    assert judge.judge(make_case(), blocked).success is False


def test_close_closes_target_and_defenses():
    target = ScriptedTarget(ScriptedTarget.Params(), CTX)
    defense = FakeDefense("input", set())
    DefendedTarget(target, [defense]).close()
    assert target.closed and defense.closed


@pytest.mark.parametrize(
    ("output", "unsafe", "category"),
    [("safe", False, None), ("unsafe\nS6", True, "S6"), (" UNSAFE ", True, None), ("hmm", None, None)],
)
def test_parse_guard_output(output, unsafe, category):
    decision = parse_guard_output(output)
    assert decision.unsafe is unsafe and decision.category == category


def test_guard_messages():
    assert guard_messages("q") == [{"role": "user", "content": "q"}]
    assert guard_messages("q", "a")[1] == {"role": "assistant", "content": "a"}


def make_filter(stage: str, reply: str | None, status: int = 200, **params) -> tuple[LlamaGuardFilter, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "guard:latest", "digest": "d-guard"}]})
        bodies.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text="placeholder error")
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply}})

    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    guard = LlamaGuardFilter(
        LlamaGuardFilter.Params(model="guard", stage=stage, retries=0, **params), CTX, client=client
    )
    return guard, bodies


def test_input_filter_classifies_request_only():
    guard, bodies = make_filter("input", "unsafe\nS2")
    screening = guard.screen(make_case(prompt="placeholder request"), None)
    assert screening.blocked and screening.reason == "unsafe (S2)"
    assert bodies[0]["messages"] == [{"role": "user", "content": "placeholder request"}]
    assert guard.name == "llama_guard_input:guard"


def test_output_filter_classifies_request_and_response():
    guard, bodies = make_filter("output", "safe")
    response = TargetResponse(text="placeholder answer", model="m", latency_ms=1)
    assert not guard.screen(make_case(prompt="placeholder request"), response).blocked
    assert bodies[0]["messages"][1] == {"role": "assistant", "content": "placeholder answer"}


@pytest.mark.parametrize("fail_closed", [False, True])
def test_classifier_failures_follow_fail_policy(fail_closed):
    guard, _ = make_filter("input", "gibberish", fail_closed=fail_closed)
    assert guard.screen(make_case(), None).blocked is fail_closed
    errored, _ = make_filter("input", None, status=404, fail_closed=fail_closed)
    screening = errored.screen(make_case(), None)
    assert screening.blocked is fail_closed and "classifier error" in screening.reason


def test_describe_reports_digest():
    guard, _ = make_filter("output", "safe")
    assert guard.describe()["model_digest"] == "d-guard"


def test_config_defenses_wrap_the_target(config_dict, write_config, tmp_path, monkeypatch):
    # Patch the filter's screen so the end-to-end run needs no Ollama.
    def fake_screen(self, case, response):
        return Screening(blocked=case.id == "jbb-2", reason="unsafe (S1)")

    monkeypatch.setattr(LlamaGuardFilter, "screen", fake_screen)
    monkeypatch.setattr(LlamaGuardFilter, "describe", lambda self: {"type": self.name})
    config_dict["defenses"] = [{"type": "llama_guard_filter", "params": {"stage": "input", "model": "guard"}}]
    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    run_dir = next((tmp_path / "runs").iterdir())
    results = {r.case.id: r for r in read_results(run_dir / RunStore.RESULTS_FILE)}
    assert results["jbb-2"].response.blocked_by == "llama_guard_input:guard: unsafe (S1)"
    assert results["jbb-2"].verdict.success is False
    assert results["jbb-1"].response.blocked_by is None
    manifest = json.loads((run_dir / RunStore.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["target"]["defenses"] == [{"type": "llama_guard_input:guard"}]
