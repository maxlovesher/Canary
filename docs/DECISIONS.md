# Design decisions

Status legend: **PROVISIONAL** = chosen by the implementation partner while the
owner was away, using the recommendation from the milestone-1 proposal; please
confirm or overturn. **ACCEPTED** = confirmed by the owner.

## D1. Milestone-1 dataset and judge semantics — ACCEPTED

JailbreakBench JBB-Behaviors (harmful split), sent as direct requests (prompt =
`Goal`), judged by refusal patterns. Reported ASR is labeled
`proxy_non_refusal` in every `metrics.json`.

- Why: it is the named jailbreak dataset; the pipeline it exercises (dataset ->
  target -> judge -> metrics) is the one every later milestone reuses.
- Cost: non-refusal overestimates true jailbreak success. Mitigated by labeling,
  by matching only the first 300 chars (ignores trailing disclaimers), and by
  milestone 5's validated LLM judge.
- Alternative: system-prompt canary extraction with an exact-match judge
  (unambiguous judge, different dataset). Natural fit for milestone 2 instead.

## D2. Component config shape: `type` + `params`, validated per component — ACCEPTED

Each component class owns a pydantic `Params` model; the registry validates the
raw `params` dict at build time. `config.py` never lists components.

- Pro: adding a component is one file; no central union to edit.
- Con: no single JSON schema for the whole config. Errors still surface before
  any model call because `build_components` runs at startup (and `redbench validate`).

## D3. Response cache: SQLite (stdlib) — ACCEPTED

Single file, atomic writes, indexed lookups, no dependency. Key = sha256 of
(target type, model digest, full request body incl. seed + sampling params).

- Including the model digest means re-pulling a model tag invalidates its cache
  (correctness over convenience). Consequence: even `read_only` replay needs
  Ollama running to look up the digest (`/api/tags`, no generation).

## D4. HTTP: `httpx`, not the `ollama` client — ACCEPTED

Thin, testable with `MockTransport`, and reusable for OpenAI-compatible
endpoints later. Retries transport errors and 408/429/5xx with exponential backoff.

## D5. Package layout — ACCEPTED

Package `redbench` at the root of the `Canary` repo (src layout). RAGBench's
conventions were not available to mirror; happy to align once shared.

## D6. Default model: `qwen3:4b`, `think: true`, `max_tokens: 2048` — ACCEPTED (placeholder model)

Chosen only because it was already pulled on the dev machine (RTX 3060 6 GB).
Model is config, never hardcoded.

Measured on 2026-10-02 (Ollama 0.15.1, qwen3:4b Q4_K_M, harmless prompts only):
this build *always* reasons. `think: false` does not disable reasoning; it leaks
untagged reasoning into the answer text (bad for any judge). With `think: true` the
reasoning goes to a separate field and only the final answer is judged. Reasoning
consumes the token budget: a 400-token budget produced no answer to "12 x 12",
while 2048 worked (800-1400 reasoning chars for simple questions).

Consequences built in: `TargetResponse` records `finish_reason` and `reasoning`;
an empty answer cut off by `max_tokens` is **unjudged** (not counted as a refusal);
metrics report `n_truncated` and the CLI warns.

Worth deciding: a non-reasoning model (e.g. an instruct variant) is ~10x cheaper
per case and avoids the issue entirely, but needs a pull.

## D7. Statistics — ACCEPTED

ASR reported with Wilson 95% intervals (hand-implemented, tested against
reference values). Target errors excluded from denominators and reported as
`n_unjudged`. Latency for cache hits reports the original call's latency.

## D8. Module-level component registries

`TARGETS`, `ATTACK_SOURCES`, `JUDGES` are module-level registries populated by
decorators at import time. This is the one piece of global state; it is
write-once at import and keeps the Factory-from-config simple. Alternative: an
explicit registry object passed around (more ceremony, no practical gain yet).

## Open questions for the owner

1. Confirm or overturn D1–D7.
2. Share RAGBench (path or repo) so CLI, run-dir and config conventions can match.
3. OK to push to the public `origin` (github.com/maxlovesher/Canary)? Nothing has been pushed.
