"""Shared Ollama plumbing for targets: request building, retries, model digest, caching.

Every ``/api/chat`` call goes through :meth:`OllamaClient.chat`, which caches the
raw response JSON under a key covering the model digest and the full request body.
Multi-step agents therefore replay exactly: each step's request (including all
earlier tool outputs) maps to one cached response.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from redbench.cache import ResponseCache, make_cache_key
from redbench.errors import CacheMissError, TargetError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_CACHE_FORMAT = 2  # bump when the cached payload shape changes


class OllamaParams(BaseModel):
    """Connection and sampling settings shared by all Ollama-backed targets."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    base_url: str = "http://localhost:11434"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: PositiveInt = 512  # per model call
    num_ctx: PositiveInt | None = None  # context window; None = Ollama default
    think: bool | None = None  # reasoning models (e.g. qwen3); None = model default
    timeout_s: float = Field(default=120.0, gt=0)
    retries: int = Field(default=2, ge=0, le=10)
    backoff_s: float = Field(default=1.0, ge=0)


def _with_default_tag(model: str) -> str:
    """Ollama treats ``qwen3`` and ``qwen3:latest`` as the same model."""
    return model if ":" in model else f"{model}:latest"


class OllamaClient:
    """Thin client around Ollama's HTTP API for one model."""

    def __init__(
        self,
        params: OllamaParams,
        *,
        seed: int,
        cache: ResponseCache | None,
        cache_namespace: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.params = params
        self.seed = seed
        self._cache = cache
        self._namespace = cache_namespace
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=params.base_url, timeout=params.timeout_s)
        self._sleep = sleep
        self._digest: str | None = None

    def build_body(self, messages: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        """A non-streaming ``/api/chat`` request with seeded sampling options."""
        body: dict[str, Any] = {
            "model": self.params.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.params.temperature,
                "num_predict": self.params.max_tokens,
                "seed": self.seed,
            },
            **extra,
        }
        if self.params.num_ctx is not None:  # only when set, so existing cache keys stay valid
            body["options"]["num_ctx"] = self.params.num_ctx
        if self.params.think is not None:
            body["think"] = self.params.think
        return body

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

    def chat(self, body: dict[str, Any], *, case_id: str) -> tuple[dict[str, Any], float, bool]:
        """Run one ``/api/chat`` request, via the cache when configured.

        Returns ``(response_json, latency_ms, cached)``; ``latency_ms`` is the original
        call's latency even on a cache hit.
        """
        key: str | None = None
        if self._cache is not None:
            key = make_cache_key(
                {
                    "format": _CACHE_FORMAT,
                    "target": self._namespace,
                    "model_digest": self.model_digest(),
                    "request": body,
                }
            )
            hit = self._cache.get(key)
            if hit is not None:
                logger.debug("cache hit for case %s", case_id)
                return hit["data"], float(hit["latency_ms"]), True
            if self._cache.read_only:
                raise CacheMissError(f"no cached response for case {case_id} (cache mode is read_only)")
        data, latency_ms = self._post_with_retries(body)
        validate_chat_response(data)
        if key is not None and self._cache is not None:
            self._cache.put(key, {"data": data, "latency_ms": latency_ms})
        return data, latency_ms, False

    def close(self) -> None:
        """Close the HTTP client if this object created it."""
        if self._owns_client:
            self._client.close()

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


def validate_chat_response(data: Any) -> None:
    """Raise ``TargetError`` unless ``data`` looks like an ``/api/chat`` reply."""
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("content", ""), str):
        keys = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise TargetError(f"unexpected Ollama response shape: keys={keys}")
    if "content" not in message and not message.get("tool_calls"):
        raise TargetError("unexpected Ollama response shape: message has neither content nor tool_calls")


def reasoning_of(message: dict[str, Any]) -> str | None:
    """The separate reasoning trace of a thinking model, if present."""
    thinking = message.get("thinking")
    return thinking if isinstance(thinking, str) and thinking else None
