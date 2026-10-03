"""Input/output classifier defense backed by a Llama Guard model on Ollama."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import Field

from redbench.defenses.base import DEFENSES, Screening, Stage
from redbench.errors import TargetError
from redbench.llama_guard import guard_messages, parse_guard_output
from redbench.records import AttackCase, TargetResponse
from redbench.registry import BuildContext
from redbench.targets.ollama_client import OllamaClient, OllamaParams

logger = logging.getLogger(__name__)


@DEFENSES.register("llama_guard_filter")
class LlamaGuardFilter:
    """Blocks requests (``stage: input``) or responses (``stage: output``) Llama Guard calls unsafe.

    ``fail_closed`` decides what happens when the classifier errors or answers
    something unparseable: block (secure, costs utility) or allow (default).
    """

    class Params(OllamaParams):
        stage: Stage
        max_tokens: int = Field(default=20, ge=1)
        fail_closed: bool = False

    def __init__(
        self,
        params: Params,
        context: BuildContext,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.params = params
        self.stage: Stage = params.stage
        self.name = f"llama_guard_{params.stage}:{params.model}"
        self._ollama = OllamaClient(
            params,
            seed=context.seed,
            cache=context.cache,
            cache_namespace=f"defense:{self.name}",
            client=client,
            sleep=sleep,
        )

    def describe(self) -> dict[str, Any]:
        """Settings and model digest (fails fast if the model is missing)."""
        return {
            "type": self.name,
            **self.params.model_dump(mode="json"),
            "model_digest": self._ollama.model_digest(),
        }

    def screen(self, case: AttackCase, response: TargetResponse | None) -> Screening:
        """Classify the request (input stage) or the request + response (output stage)."""
        text = None if self.stage == "input" else (response.text if response is not None else "")
        body = self._ollama.build_body(guard_messages(case.prompt, text))
        try:
            data, latency_ms, _cached = self._ollama.chat(body, case_id=case.id)
        except TargetError as exc:
            logger.warning("%s failed on case %s: %s", self.name, case.id, exc)
            return Screening(blocked=self.params.fail_closed, reason=f"classifier error: {exc}")
        decision = parse_guard_output(data["message"].get("content", ""))
        if decision.unsafe is None:
            return Screening(
                blocked=self.params.fail_closed,
                reason=f"unparseable classifier output: {decision.raw[:60]!r}",
                latency_ms=latency_ms,
            )
        if decision.unsafe:
            return Screening(
                blocked=True, reason=f"unsafe ({decision.category or 'unspecified'})", latency_ms=latency_ms
            )
        return Screening(blocked=False, reason="safe", latency_ms=latency_ms)

    def close(self) -> None:
        """Release the HTTP client."""
        self._ollama.close()
