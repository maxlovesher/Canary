# Canary: measuring LLM attacks *and* what defenses cost

**TL;DR.** Canary is a small, config-driven red-teaming harness for local LLMs. On
qwen3:4b it shows two things that headline "attack success rate" numbers usually
hide: (1) three reasonable judges looking at the *same* 100 responses report 6%, 0%
and 6% attack success while agreeing on just one case, and (2) the defense that looks
best on security (a hardened system prompt, ASR 6% -> 1%) makes the model refuse 69% of
benign requests. Every number below is measured locally and labeled with how it was
judged; none is validated against human labels yet.

## Why

Red-teaming results are usually reported as one number: attack success rate (ASR).
That number depends on two choices that are rarely shown: *who decides an attack
succeeded* (the judge) and *what the defense costs* in normal use. Canary makes both
explicit: every run records which judge produced its ASR, several judges can score the
same responses, and every defense is measured on benign prompts as well as harmful ones.

## What I built

```
config.yaml -> factory -> target (Ollama chat model, optionally wrapped by defenses)
                       -> attack sources (JailbreakBench)
                       -> primary judge + secondary judges
runner: case -> target -> judges -> results.jsonl -> metrics.json (Wilson CIs)
analysis: canary label / agreement / tradeoff / report
```

- **Config-driven strategy pattern.** Targets, attack sources, judges and defenses
  are registered classes with their own pydantic `Params`; a YAML config picks them
  by name and everything is validated before the first model call.
- **Reproducibility.** Every model call is cached in SQLite under the model digest and
  the full request. Re-judging a run, or adding a defense that screens existing
  answers, replays from the cache in seconds; `read_only` mode makes replay strict.
- **Judges.** A regex refusal judge, an LLM rubric judge, and Llama Guard; all run on
  the same responses. A blind labeling CLI and hand-written agreement metrics
  (accuracy with Wilson CI, precision, recall, Cohen's κ) score judges against humans.
- **Defenses.** A hardened system prompt and Llama Guard filters on the request
  (input) or the answer (output), measured on 100 harmful and 100 benign prompts.
- **Report.** `canary report` builds a static HTML page from aggregate files only;
  prompts and responses never leave the machine.
- **Engineering.** 191 tests, synthetic fixtures only, three runtime dependencies
  (pydantic, pyyaml, httpx), metrics implemented in the repo.

## Results (qwen3:4b, RTX 3060 6 GB, n = 100 per condition)

| | Result | How it was judged |
|---|---|---|
| Undefended, direct JailbreakBench requests | ASR 6.0% [2.8, 12.5] | refusal patterns (proxy) |
| Same responses, LLM rubric judge | 0.0% [0.0, 3.7] | qwen3:4b judging itself |
| Same responses, Llama Guard 3 1B | 6.0% [2.8, 12.5], 1 case shared with row 1 | Llama Guard taxonomy |
| Hardened system prompt | ASR 1.0%, false refusals 18% -> 69% | refusal patterns |
| Llama Guard input filter | ASR 1.0%, false refusals 18% -> 31%; 95/100 harmful requests blocked in 0.2 s | refusal patterns |
| Llama Guard output filter | ASR 5.0%, false refusals 18% -> 33% | refusal patterns |

Full tables, provenance and caveats: [RESULTS.md](RESULTS.md) (R1–R4).

## What I learned

1. **The judge is the measurement.** Equal headline rates hid near-total disagreement
   on *which* responses succeeded. The refusal judge measures "didn't refuse"; Llama
   Guard measures its own policy taxonomy (5 of its 6 flags were "specialized
   advice"); the rubric judge measures "meaningfully helped". Only human labels can
   say which matters, so judge validation moved ahead of new attacks in the roadmap.
2. **Defenses must be priced in utility.** The hardened prompt told the model to answer
   benign requests fully and it still refused 69% of them. Without the benign run it
   would have looked like the best defense.
3. **Small differences need the right test.** Every condition saw the same 100
   prompts, so Canary pairs them (exact McNemar). Even paired, no defense lowered ASR
   significantly (best p = 0.062: 5 baseline successes removed, none added), while
   every defense added false refusals with p < 0.001. A single ASR number would have
   suggested the opposite.
4. **Reasoning models break naive harnesses.** qwen3 ignores `think: false` (reasoning
   leaks into the answer), and reasoning can consume the whole token budget: an
   LLM judge with 1,024 tokens returned no verdict on 93 of 100 cases. Canary now
   separates reasoning from answers, records truncation, and treats a cut-off empty
   answer as unjudged rather than as a refusal.
5. **Fail-open hides bugs.** Llama Guard once answered a bare `S6` without the word
   "unsafe"; the filter silently allowed it. It surfaced only because I logged
   unparseable classifier output while checking a claim in the results. Fixed and
   re-measured from cache (one number changed).

## Limitations

- **No human labels yet**, so every ASR above is a proxy or an unvalidated LLM judge.
- **One model, one attack style.** Direct requests barely succeed against qwen3:4b, so
  this setup cannot separate the defenses on security. Jailbreak transforms, an
  attacker LLM and agent prompt injection (milestones 2–4) are not built.
- **The benign set is borderline by design** (JailbreakBench's topic-matched benign
  split), so the 18% baseline false-refusal rate overstates over-refusal on everyday use.
- **Self-judging.** The rubric judge is the same model as the target.

## Next

1. Label the 100 baseline responses (`canary label`) and score every judge
   (`canary agreement`); pick the judge used for all later results.
2. Add attacks that move the baseline (transforms, multi-turn) so defenses can be
   separated on security, not only on cost.
3. Finish the agent target (mock tools, indirect injection, canary-leak judge) and the
   two agent-only defenses (delimiting untrusted content, tool permissions).

See also: [COMPARISON.md](COMPARISON.md) (garak and PyRIT),
[DECISIONS.md](DECISIONS.md) (every design decision and why).
