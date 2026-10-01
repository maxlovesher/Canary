"""Plain chat-LLM target served by a local Ollama instance (``POST /api/chat``)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from redbench.cache import make_cache_key
from redbench.errors import CacheMissError, TargetError
from redbench.records import AttackCase, TargetResponse
from redbench.registry import BuildContext
from redbench.targets.base import TARGETS

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def _with_default_tag(model: str) -> str:
    """Ollama treats ``qwen3`` and ``qwen3:latest`` as the same model."""
    return model if ":" in model else f"{model}:latest"


@TARGETS.register("ollama_chat")
class OllamaChatTarget:
    """Single-turn chat: optional system prompt plus the attack prompt as one user turn.

    Responses are cached (when a cache is configured) under a key covering the
    model digest and the full request body, including seed and sampling params.
    """

    class Params(BaseModel):
        model_config = ConfigDict(extra="forbid")

        model: str = Field(min_length=1)
        base_url: str = "http://localhost:11434"
        system_prompt: str | None = None
        temperature: float = Field(default=0.0, ge=0.0, le=2.0)
        max_tokens: PositiveInt = 512
        think: bool | None = None  # reasoning models (e.g. qwen3); None = model default
        timeout_s: float = Field(default=120.0, gt=0)
        retries: int = Field(default=2, ge=0, le=10)
        backoff_s: float = Field(default=1.0, ge=0)

    name = "ollama_chat"

    def __init__(
        self,
        params: Params,
        context: BuildContext,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.params = params
        self._seed = context.seed
        self._cache = context.cache
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=params.base_url, timeout=params.timeout_s)
        self._sleep = sleep
        self._digest: str | None = None

    # -- public API ---------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Settings plus the exact model digest, for the run manifest."""
        return {
            "type": self.name,
            **self.params.model_dump(mode="json"),
            "seed": self._seed,
            "model_digest": self.model_digest(),
        }

    def model_digest(self) -> str:
        """Digest of the configured model, looked up once via ``GET /api/tags``."""
        if self._digest is None:
            try:
                response = self._client.get("/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
            except (httpx.HTTPError, ValueError, AttributeError) as exc:
                raise TargetError(f"cannot list Ollama models at {self.params.base_url}: {exc}") from exc
            wanted = _with_default_tag(self.params.model)
            for entry in models:
                if _with_default_tag(str(entry.get("name", ""))) == wanted and entry.get("digest"):
                    self._digest = str(entry["digest"])
                    break
            else:
                raise TargetError(
                    f"model {self.params.model!r} is not available in Ollama; run `ollama pull {self.params.model}`"
                )
        return self._digest

    def generate(self, case: AttackCase) -> TargetResponse:
        """Send one case to the model, using the response cache when configured."""
        body = self._request_body(case)
        key: str | None = None
        if self._cache is not None:
            key = make_cache_key({"target": self.name, "model_digest": self.model_digest(), "request": body})
            hit = self._cache.get(key)
            if hit is not None:
                logger.debug("cache hit for case %s", case.id)
                return TargetResponse.model_validate({**hit, "cached": True})
            if self._cache.read_only:
                raise CacheMissError(f"no cached response for case {case.id} (cache mode is read_only)")
        data, latency_ms = self._post_with_retries(body)
        response = self._parse(data, latency_ms)
        if key is not None and self._cache is not None:
            self._cache.put(key, response.model_dump(exclude={"cached"}))
        return response

    def close(self) -> None:
        """Close the HTTP client if this target created it."""
        if self._owns_client:
            self._client.close()

    # -- internals ----------------------------------------------------------

    def _request_body(self, case: AttackCase) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if self.params.system_prompt:
            messages.append({"role": "system", "content": self.params.system_prompt})
        messages.append({"role": "user", "content": case.prompt})
        body: dict[str, Any] = {
            "model": self.params.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.params.temperature,
                "num_predict": self.params.max_tokens,
                "seed": self._seed,
            },
        }
        if self.params.think is not None:
            body["think"] = self.params.think
        return body

    def _post_with_retries(self, body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        """POST ``/api/chat``; retry transport errors and transient HTTP statuses.

        Returns the parsed JSON and the latency of the successful attempt in ms.
        """
        attempts = self.params.retries + 1
        last_error = "no attempt made"
        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            try:
                response = self._client.post("/api/chat", json=body)
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc!r}"
            else:
                latency_ms = (time.perf_counter() - start) * 1000
                if response.status_code == 200:
                    try:
                        return response.json(), latency_ms
                    except ValueError as exc:
                        raise TargetError(f"Ollama returned invalid JSON: {exc}") from exc
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in _RETRYABLE_STATUS:
                    raise TargetError(last_error)
            if attempt < attempts:
                delay = self.params.backoff_s * 2 ** (attempt - 1)
                logger.warning(
                    "Ollama attempt %d/%d failed (%s); retrying in %.1fs", attempt, attempts, last_error, delay
                )
                self._sleep(delay)
        raise TargetError(f"Ollama request failed after {attempts} attempts: {last_error}")

    def _parse(self, data: dict[str, Any], latency_ms: float) -> TargetResponse:
        message = data.get("message") if isinstance(data, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise TargetError(
                f"unexpected Ollama response shape: keys={sorted(data) if isinstance(data, dict) else type(data)}"
            )
        thinking = message.get("thinking")
        return TargetResponse(
            text=message["content"],
            model=str(data.get("model") or self.params.model),
            latency_ms=latency_ms,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            finish_reason=data.get("done_reason"),
            reasoning=thinking if isinstance(thinking, str) and thinking else None,
        )
