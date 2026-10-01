"""OllamaChatTarget against an in-process mock of the Ollama HTTP API."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from redbench.cache import ResponseCache
from redbench.errors import CacheMissError, TargetError
from redbench.registry import BuildContext
from redbench.targets.ollama_chat import OllamaChatTarget
from tests.helpers import make_case

TAGS = {
    "models": [{"name": "qwen3:4b", "digest": "sha256digest-qwen3-4b"}, {"name": "tiny:latest", "digest": "d-tiny"}]
}


def chat_reply(content: str = "placeholder reply", thinking: str | None = None, done_reason: str = "stop") -> dict:
    message = {"role": "assistant", "content": content}
    if thinking is not None:
        message["thinking"] = thinking
    return {
        "model": "qwen3:4b",
        "message": message,
        "prompt_eval_count": 11,
        "eval_count": 22,
        "done_reason": done_reason,
    }


class FakeOllama:
    """Records requests; ``chat`` is a list of responses (or exceptions) served in order."""

    def __init__(self, chat: list[httpx.Response | Exception] | None = None, tags: dict | None = None) -> None:
        self.chat = list(chat or [httpx.Response(200, json=chat_reply())])
        self.tags = tags if tags is not None else TAGS
        self.chat_bodies: list[dict] = []
        self.tag_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.tag_calls += 1
            return httpx.Response(200, json=self.tags)
        if request.url.path == "/api/chat":
            self.chat_bodies.append(json.loads(request.content))
            item = self.chat.pop(0) if len(self.chat) > 1 else self.chat[0]
            if isinstance(item, Exception):
                raise item
            return item
        return httpx.Response(404)


def make_target(
    fake: FakeOllama,
    *,
    cache: ResponseCache | None = None,
    sleeps: list[float] | None = None,
    **params,
) -> OllamaChatTarget:
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(fake.handler))
    sleep: Callable[[float], None] = sleeps.append if sleeps is not None else (lambda _s: None)
    return OllamaChatTarget(
        OllamaChatTarget.Params(model=params.pop("model", "qwen3:4b"), **params),
        BuildContext(seed=1234, cache=cache),
        client=client,
        sleep=sleep,
    )


def test_request_body_and_parsed_response():
    fake = FakeOllama()
    target = make_target(fake, system_prompt="Be helpful.", temperature=0.0, max_tokens=64, think=False)
    response = target.generate(make_case(prompt="placeholder prompt"))

    body = fake.chat_bodies[0]
    assert body["messages"] == [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "placeholder prompt"},
    ]
    assert body["options"] == {"temperature": 0.0, "num_predict": 64, "seed": 1234}
    assert body["stream"] is False
    assert body["think"] is False
    assert response.text == "placeholder reply"
    assert response.input_tokens == 11 and response.output_tokens == 22
    assert response.cached is False
    assert response.latency_ms >= 0


def test_reasoning_and_finish_reason_are_kept_separate_from_answer():
    fake = FakeOllama(
        chat=[httpx.Response(200, json=chat_reply("", thinking="placeholder reasoning", done_reason="length"))]
    )
    response = make_target(fake, think=True).generate(make_case())
    assert response.text == ""
    assert response.reasoning == "placeholder reasoning"
    assert response.finish_reason == "length" and response.truncated


def test_no_system_prompt_and_no_think_key_by_default():
    fake = FakeOllama()
    make_target(fake).generate(make_case())
    body = fake.chat_bodies[0]
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert "think" not in body


def test_retries_transient_errors_with_exponential_backoff():
    fake = FakeOllama(
        chat=[httpx.Response(503), httpx.ConnectError("down"), httpx.Response(200, json=chat_reply("ok"))]
    )
    sleeps: list[float] = []
    response = make_target(fake, sleeps=sleeps, retries=2, backoff_s=0.5).generate(make_case())
    assert response.text == "ok"
    assert sleeps == [0.5, 1.0]


def test_gives_up_after_retries():
    fake = FakeOllama(chat=[httpx.Response(500)])
    with pytest.raises(TargetError, match="after 3 attempts"):
        make_target(fake, retries=2).generate(make_case())
    assert len(fake.chat_bodies) == 3


def test_non_retryable_status_fails_immediately():
    fake = FakeOllama(chat=[httpx.Response(404, text="model not found")])
    with pytest.raises(TargetError, match="HTTP 404"):
        make_target(fake, retries=3).generate(make_case())
    assert len(fake.chat_bodies) == 1


def test_malformed_response_raises():
    fake = FakeOllama(chat=[httpx.Response(200, json={"unexpected": True})])
    with pytest.raises(TargetError, match="unexpected Ollama response shape"):
        make_target(fake).generate(make_case())


def test_model_digest_lookup_and_default_tag():
    fake = FakeOllama()
    assert make_target(fake, model="tiny").model_digest() == "d-tiny"
    target = make_target(fake)
    assert target.describe()["model_digest"] == "sha256digest-qwen3-4b"
    target.describe()
    assert fake.tag_calls == 2  # once per target instance, then memoized


def test_missing_model_gives_pull_hint():
    with pytest.raises(TargetError, match="ollama pull nope"):
        make_target(FakeOllama(), model="nope").model_digest()


def test_cache_hit_skips_backend(tmp_path):
    fake = FakeOllama()
    with ResponseCache(tmp_path / "c.sqlite") as cache:
        first = make_target(fake, cache=cache).generate(make_case())
        second = make_target(fake, cache=cache).generate(make_case())
    assert len(fake.chat_bodies) == 1
    assert first.cached is False and second.cached is True
    assert second.text == first.text and second.latency_ms == first.latency_ms


def test_cache_key_depends_on_seed_sensitive_request(tmp_path):
    fake = FakeOllama()
    with ResponseCache(tmp_path / "c.sqlite") as cache:
        make_target(fake, cache=cache, temperature=0.0).generate(make_case())
        make_target(fake, cache=cache, temperature=0.7).generate(make_case())
    assert len(fake.chat_bodies) == 2


def test_read_only_cache_miss_raises(tmp_path):
    path = tmp_path / "c.sqlite"
    ResponseCache(path).close()
    fake = FakeOllama()
    with ResponseCache(path, read_only=True) as cache, pytest.raises(CacheMissError):
        make_target(fake, cache=cache).generate(make_case())
    assert fake.chat_bodies == []
