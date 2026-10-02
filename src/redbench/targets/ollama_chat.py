"""Plain chat-LLM target served by a local Ollama instance (``POST /api/chat``)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from redbench.records import AttackCase, TargetResponse
from redbench.registry import BuildContext
from redbench.targets.base import TARGETS
from redbench.targets.ollama_client import OllamaClient, OllamaParams, reasoning_of


@TARGETS.register("ollama_chat")
class OllamaChatTarget:
    """Single-turn chat: optional system prompt plus the attack prompt as one user turn.

    Responses are cached (when a cache is configured) under a key covering the
    model digest and the full request body, including seed and sampling params.
    """

    class Params(OllamaParams):
        system_prompt: str | None = None

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
        self._ollama = OllamaClient(
            params, seed=context.seed, cache=context.cache, cache_namespace=self.name, client=client, sleep=sleep
        )

    def describe(self) -> dict[str, Any]:
        """Settings plus the exact model digest, for the run manifest."""
        return {
            "type": self.name,
            **self.params.model_dump(mode="json"),
            "seed": self._ollama.seed,
            "model_digest": self.model_digest(),
        }

    def model_digest(self) -> str:
        """Digest of the configured model."""
        return self._ollama.model_digest()

    def generate(self, case: AttackCase) -> TargetResponse:
        """Send one case to the model."""
        messages: list[dict[str, Any]] = []
        if self.params.system_prompt:
            messages.append({"role": "system", "content": self.params.system_prompt})
        messages.append({"role": "user", "content": case.prompt})
        data, latency_ms, cached = self._ollama.chat(self._ollama.build_body(messages), case_id=case.id)
        message = data["message"]
        return TargetResponse(
            text=message.get("content", ""),
            model=str(data.get("model") or self.params.model),
            latency_ms=latency_ms,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            finish_reason=data.get("done_reason"),
            reasoning=reasoning_of(message),
            cached=cached,
        )

    def close(self) -> None:
        """Release the HTTP client."""
        self._ollama.close()
