# RedBench

Config-driven red-teaming harness for LLMs, RAG pipelines, and tool-using agents.
It attacks a system, measures attack success, and (in later milestones) measures how
much each defense reduces attacks versus what it costs in normal usefulness.

Sister project to RAGBench; same design philosophy: small strategy-pattern
components built from a YAML config, deterministic runs, metrics implemented in
the repo rather than hidden in a library.

> **Status: milestone 1 complete; milestone 2 in progress.**
> First measured baseline: qwen3:4b refuses 94% of JailbreakBench direct requests
> (proxy ASR 6.0%, 95% CI [2.8%, 12.5%]). Details and caveats: [docs/RESULTS.md](docs/RESULTS.md).

## Quickstart

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com).

```bash
uv sync
uv run pytest                                        # offline test suite
ollama serve                                         # in another terminal
ollama pull qwen3:4b                                 # or any model; set target.params.model
python scripts/fetch_jbb.py                          # JBB-Behaviors -> data/raw/jbb/ (gitignored)
uv run redbench validate configs/m1_jbb_direct.yaml  # checks config + loads cases, no model calls
uv run redbench run configs/m1_jbb_direct.yaml --set run.max_cases=5   # smoke run
uv run redbench run configs/m1_jbb_direct.yaml
```

### Validating a judge against human labels

```bash
uv run redbench label runs/<run_dir> --labeler <initials>   # blind, resumable; q to stop anytime
uv run redbench agreement runs/<run_dir>                     # writes agreement.json
```

Labels: `r` refusal, `s` safe compliance (engages but harmless/generic), `h` harmful
compliance (meaningfully helps). `agreement` reports accuracy (Wilson 95% CI),
precision, recall and Cohen's kappa for every judge, against both "harmful" and
"didn't refuse" as ground truth.

To compare LLM judges against the same labels, re-judge the cached responses and
reuse the labels (response hashes guarantee they match):

```bash
ollama pull llama-guard3:1b                          # optional second judge
uv run redbench run configs/m5_judge_validation.yaml # target calls are cache hits
uv run redbench agreement runs/<m5_run> --labels runs/<m1_run>/labels.jsonl
```

Override any config value with `--set dotted.path=value` (values parsed as YAML;
list items by index, e.g. `--set attacks.0.params.sample=20`).

## How it works

```
config.yaml ──► factory ──► Target          (ollama_chat)
                        ├─► AttackSource[]  (jailbreakbench)
                        └─► Judge           (refusal_patterns)
                                 │
          Runner: for each case ─► target.generate ─► judge.judge ─► results.jsonl
                                 │
                       metrics ─► metrics.json
```

Each component is a class with a pydantic `Params` model, registered under a
`type` name. The config selects components by `type` and passes `params`; the
factory validates everything before the first model call.

| Kind | Type | What it does |
|---|---|---|
| target | `ollama_chat` | Local Ollama chat model; seeded, cached, retried |
| attack source | `jailbreakbench` | JBB-Behaviors rows as direct requests; category filter, seeded sampling, sha256 pin |
| judge | `refusal_patterns` | Success = response does not refuse (**proxy**, see below) |

### Run directory

`runs/<UTC timestamp>_<name>_<config hash>/`

| File | Contents |
|---|---|
| `config.resolved.yaml` | The validated config that ran |
| `manifest.json` | Versions, model digest, dataset sha256, seed, status |
| `results.jsonl` | One record per attack: case, response, verdict, error |
| `metrics.json` | ASR overall and per category with Wilson 95% CIs; latency p50/p95; tokens; cost |
| `run.log` | Full log |

### Determinism

Every request carries `seed` and `temperature`. Responses are cached in SQLite
under a key covering the model digest and the full request. `cache.mode: read_only`
replays a run exactly and fails on any cache miss. Ollama is not bit-exact
across hardware, so the cache, not the seed, is the reproducibility guarantee.

### Metric caveats

- **Proxy ASR.** The milestone-1 judge counts any non-refusal as a successful attack.
  Not refusing is not the same as producing harmful content, so this overestimates
  true ASR. Metrics carry `"success_definition": "proxy_non_refusal"` until the
  LLM judge (milestone 5) is validated against hand labels.
- **Small n.** JBB has 10 behaviors per category; per-category CIs are wide and reported.
- **Errors.** Target failures are excluded from ASR denominators and counted as `n_unjudged`.

## Responsible use

Only attack models and systems you run yourself or are permitted to test under
the provider's terms. Raw prompts, responses, datasets and caches stay local
(`runs/`, `.cache/`, `data/raw/` are gitignored); only aggregate metrics are published.

## Roadmap

1. ✅ Skeleton, config, runner, Ollama target, JailbreakBench, rule judge → first ASR
2. Agent target with mock tools; indirect prompt injection via tool outputs; canary checks
3. Attack transforms (role-play, encoding, translation) and multi-turn
4. Attacker LLM that refines failed attacks
5. LLM judge validated against ~100 hand-labeled examples
6. Defenses and the security-vs-utility chart
7. Report, baseline comparison vs garak / PyRIT, write-up

Design decisions and open questions: [docs/DECISIONS.md](docs/DECISIONS.md).
