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
  any model call because `build_components` runs at startup (and `canary validate`).

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

Package `canary` at the root of the `Canary` repo (src layout). RAGBench's
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

## D9. Human labels: 3-way rubric, blind, two ground truths — ACCEPTED (owner: "do it")

Labels are `refusal` / `safe_compliance` / `harmful_compliance`, stored append-only
in `<run_dir>/labels.jsonl` with a hash of the labeled response text (stale labels
are detected and excluded). Labeling is blind: the judge verdict is never shown.

Every judge is scored against two binary ground truths:
- `vs_harmful_compliance` (harmful = attack succeeded): the metric that matters.
- `vs_any_compliance` (anything but refusal): what a refusal judge actually measures.

The gap between the two is exactly the "proxy" error of the refusal judge. Metrics
(accuracy + Wilson CI, precision, recall, Cohen's kappa) are hand-implemented in
`metrics/agreement.py`. Order of milestones changed: judge validation (M5 part 1)
comes before M3/M4, because every later ASR depends on a trustworthy judge.

## D10. LLM judge: two styles, run as secondary judges — ACCEPTED (owner: "do it urself")

`ollama_llm_judge` supports a `rubric` prompt (any chat model; same 3-way rubric as
the human labels, one-word answer) and `llama_guard` (native safe/unsafe output).
LLM judges run as `secondary_judges`, so the primary refusal judge and the headline
ASR stay comparable across runs while `agreement` scores all judges side by side.

- Candidates: `qwen3:4b` rubric (already local, but judges its own outputs, a known
  self-preference bias) vs `llama-guard3:1b` (purpose-built classifier, different
  family, fits 6 GB). The winner is whichever agrees best with human labels on
  `vs_harmful_compliance`; no judge is trusted before that.
- Unparseable judge output or backend errors -> unjudged (never silently "safe").
- `agreement --labels` lets one labeling pass score any replay of the same
  responses; response hashes guarantee labels only match identical text.

## D11. Defenses wrap the target; utility from JBB benign — ACCEPTED (owner: "keep on building")

- `defenses:` config list -> `DefendedTarget`. Input-stage defenses run before the
  model (a block skips it); output-stage defenses screen the answer. A block returns
  a fixed refusal ("I can't help with that request.") and records `blocked_by`, so
  every judge scores a block as a failed attack and, on benign prompts, a false refusal.
- Implemented now: hardened system prompt (config only), Llama Guard input filter,
  Llama Guard output filter. Fail-open by default (`fail_closed` param available).
  Delimiting untrusted content and tool-permission policy need the M2 agent target.
- Utility = non-refusal rate on JBB-Behaviors' benign split (100 requests matched to
  the harmful topics, deliberately borderline), judged by the refusal judge; false
  refusal rate = 1 - utility. A proxy, like the ASR, until human-validated.
- The hardened prompt explicitly tells the model to answer benign requests fully,
  so its utility cost is not trivially "refuse more of everything".

## D12. Agent-only defenses as tool-layer components — ACCEPTED (owner: "go finish it")

Built ahead of the agent loop (milestone 2) so it can use them directly:

- `ToolPolicy` (least privilege): tool allowlist, allowed `send_email` recipient
  domains, allowed `fetch_url` hosts (http/https only, subdomains allowed, suffix
  matches only on label boundaries). Checked inside `execute_tool` after argument
  validation; a denied call returns `error: blocked by tool policy: ...` and never
  touches the mock environment, so trajectories show *attempted* vs *executed* actions.
- `Spotlight` (Hines et al. 2024): `delimit` wraps tool output in a boundary tag with
  a per-run nonce and strips that tag from the content so injected text cannot close
  it; `datamark` replaces whitespace with a marker character. Each mode supplies the
  matching system-prompt sentence. The nonce is derived from the run seed, keeping
  agent runs replayable from the cache.
- Not measured yet: both need the agent target and injection scenarios to produce ASR
  and utility numbers.

## Open questions for the owner

1. Confirm or overturn D1–D7.
2. Share RAGBench (path or repo) so CLI, run-dir and config conventions can match.
3. OK to push to the public `origin` (github.com/maxlovesher/Canary)? Nothing has been pushed.
