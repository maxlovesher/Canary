"""OllamaLLMJudge against an in-process mock of the Ollama HTTP API."""

from __future__ import annotations

import json

import httpx
import pytest

from redbench.cache import ResponseCache
from redbench.judges.llm_judge import RUBRIC_SYSTEM_PROMPT, OllamaLLMJudge
from redbench.records import TargetResponse
from redbench.registry import BuildContext
from tests.helpers import make_case

TAGS = {"models": [{"name": "judge-model:latest", "digest": "d-judge"}]}


class FakeJudgeBackend:
    def __init__(self, replies: list[str] | None = None, status: int = 200) -> None:
        self.replies = list(replies or ["SAFE"])
        self.status = status
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        self.bodies.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(self.status, text="placeholder error")
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return httpx.Response(200, json={"model": "judge-model", "message": {"role": "assistant", "content": reply}})


def make_judge(backend: FakeJudgeBackend, cache: ResponseCache | None = None, **params) -> OllamaLLMJudge:
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(backend.handler))
    return OllamaLLMJudge(
        OllamaLLMJudge.Params(model=params.pop("model", "judge-model"), retries=0, **params),
        BuildContext(seed=1, cache=cache),
        client=client,
    )


def answer(text: str = "placeholder answer", **kwargs) -> TargetResponse:
    return TargetResponse(text=text, model="target", latency_ms=1, **kwargs)


@pytest.mark.parametrize(
    ("reply", "success"),
    [
        ("HARMFUL", True),
        ("SAFE", False),
        ("REFUSAL", False),
        ("harmful", True),
        ("Options are REFUSAL, SAFE or HARMFUL. Final answer: SAFE", False),  # last label wins
        ("<think>could be HARMFUL</think>REFUSAL", False),  # reasoning block ignored
    ],
)
def test_rubric_parsing(reply, success):
    verdict = make_judge(FakeJudgeBackend([reply])).judge(make_case(), answer())
    assert verdict.success is success


def test_rubric_request_shape():
    backend = FakeJudgeBackend()
    judge = make_judge(backend, think=True, num_ctx=8192)
    judge.judge(make_case(prompt="placeholder request"), answer("placeholder answer"))
    body = backend.bodies[0]
    assert body["messages"][0] == {"role": "system", "content": RUBRIC_SYSTEM_PROMPT}
    assert body["messages"][1]["content"] == "REQUEST:\nplaceholder request\n\nRESPONSE:\nplaceholder answer"
    assert body["options"]["num_ctx"] == 8192 and body["think"] is True
    assert judge.name == "llm_rubric:judge-model"


@pytest.mark.parametrize(
    ("reply", "success", "reason"),
    [
        ("unsafe\nS2", True, "unsafe (S2)"),
        ("unsafe", True, "unsafe (unspecified)"),
        ("safe", False, "safe"),
        ("I think it is fine", None, "unparseable"),
    ],
)
def test_llama_guard_parsing(reply, success, reason):
    verdict = make_judge(FakeJudgeBackend([reply]), style="llama_guard").judge(make_case(), answer())
    assert verdict.success is success
    assert reason in verdict.reason


def test_llama_guard_sends_conversation_without_system_prompt():
    backend = FakeJudgeBackend(["safe"])
    judge = make_judge(backend, style="llama_guard")
    judge.judge(make_case(prompt="placeholder request"), answer("placeholder answer"))
    assert backend.bodies[0]["messages"] == [
        {"role": "user", "content": "placeholder request"},
        {"role": "assistant", "content": "placeholder answer"},
    ]
    assert "think" not in backend.bodies[0]
    assert judge.name == "llm_llama_guard:judge-model"


def test_unparseable_and_backend_errors_are_unjudged():
    assert make_judge(FakeJudgeBackend(["maybe?"])).judge(make_case(), answer()).success is None
    verdict = make_judge(FakeJudgeBackend(status=404)).judge(make_case(), answer())
    assert verdict.success is None and "judge error" in verdict.reason


def test_judge_out_of_tokens_is_reported():
    class Truncating(FakeJudgeBackend):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json=TAGS)
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": "", "thinking": "..."}, "done_reason": "length"}
            )

    verdict = make_judge(Truncating()).judge(make_case(), answer())
    assert verdict.success is None and "ran out of tokens" in verdict.reason


def test_empty_and_truncated_answers_skip_the_model():
    backend = FakeJudgeBackend()
    judge = make_judge(backend)
    assert judge.judge(make_case(), answer("")).success is False
    assert judge.judge(make_case(), answer("", finish_reason="length")).success is None
    assert backend.bodies == []


def test_judge_calls_are_cached(tmp_path):
    backend = FakeJudgeBackend(["HARMFUL"])
    with ResponseCache(tmp_path / "c.sqlite") as cache:
        first = make_judge(backend, cache=cache).judge(make_case(), answer())
        second = make_judge(backend, cache=cache).judge(make_case(), answer())
    assert first == second and len(backend.bodies) == 1


def test_describe_reports_digest():
    info = make_judge(FakeJudgeBackend()).describe()
    assert info["model_digest"] == "d-judge" and info["type"] == "llm_rubric:judge-model"
    assert "system_prompt" not in info
