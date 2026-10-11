# Canary

[![CI](https://github.com/maxlovesher/Canary/actions/workflows/ci.yml/badge.svg)](https://github.com/maxlovesher/Canary/actions/workflows/ci.yml)

Config-driven red-teaming harness for LLMs, RAG pipelines, and tool-using agents.
It attacks a system, measures attack success, and (in later milestones) measures how
much each defense reduces attacks versus what it costs in normal usefulness.

Sister project to RAGBench; same design philosophy: small strategy-pattern
components built from a YAML config, deterministic runs, metrics implemented in
the repo rather than hidden in a library.

> **Status:** milestones 1 and 6 done; 5 built and awaiting human labels; 2 partly built.
> All numbers are measured locally on qwen3:4b, with proxy judges until labels land.
> Details and caveats: [docs/RESULTS.md](docs/RESULTS.md).

![Security vs utility](reports/m6_defenses/tradeoff.svg)

| Finding (proxy judges, n = 100 each) | |
|---|---|
| Undefended JailbreakBench direct requests | ASR 6.0% [2.8, 12.5] |
| Three judges on the same responses | 6.0% / 0.0% / 6.0%, sharing just 1 flagged case; pairwise κ 0.00–0.11 |
| Hardened system prompt | ASR 1.0%, but false refusals 18% → 69% |
| Llama Guard input filter | ASR 1.0%, false refusals 18% → 31%; harmful requests rejected in 0.2 s |
| Llama Guard output filter | ASR 5.0%, false refusals 18% → 33% |

The HTML report (`uv run canary report` → `reports/index.html`) shows all of it in one page.
Start with the [write-up](docs/WRITEUP.md); [how Canary compares to garak and PyRIT](docs/COMPARISON.md).

## Quickstart

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com).

```bash
uv sync
uv run pytest                                        # offline test suite
ollama serve                                         # in another terminal
ollama pull qwen3:4b                                 # or any model; set target.params.model
python scripts/fetch_jbb.py                          # JBB-Behaviors -> data/raw/jbb/ (gitignored)
uv run canary validate configs/m1_jbb_direct.yaml  # checks config + loads cases, no model calls
uv run canary run configs/m1_jbb_direct.yaml --set run.max_cases=5   # smoke run
uv run canary run configs/m1_jbb_direct.yaml
```

### Validating a judge against human labels

```bash
uv run canary label runs/<run_dir> --labeler <initials>   # blind, resumable; q to stop anytime
uv run canary agreement runs/<run_dir>                     # writes agreement.json
```

Labels: `r` refusal, `s` safe compliance (engages but harmless/generic), `h` harmful
compliance (meaningfully helps). `agreement` reports accuracy (Wilson 95% CI),
precision, recall and Cohen's kappa for every judge, against both "harmful" and
"didn't refuse" as ground truth.

To compare LLM judges against the same labels, re-judge the cached responses and
reuse the labels (response hashes guarantee they match):

```bash
ollama pull llama-guard3:1b                          # optional second judge
uv run canary run configs/m5_judge_validation.yaml # target calls are cache hits
uv run canary agreement runs/<m5_run> --labels runs/<m1_run>/labels.jsonl
```

### Defenses and the security-vs-utility tradeoff

```bash
python scripts/fetch_jbb.py --split benign           # benign prompts for utility
uv run python scripts/run_defense_matrix.py          # 4 conditions x harmful/benign
uv run canary report                               # rebuild reports/index.html
```

Defenses go in a config's `defenses:` list and wrap the target: `llama_guard_filter`
with `stage: input` (screens requests) or `stage: output` (screens answers). A
hardened system prompt is just a different `target.params.system_prompt`.
`canary tradeoff --pair LABEL HARMFUL_RUN BENIGN_RUN ...` compares any runs.

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
| judge | `ollama_llm_judge` | LLM judge: 3-way rubric prompt, or Llama Guard's safe/unsafe; run as `secondary_judges` |
| defense | `llama_guard_filter` | Llama Guard screens requests (`input`) or answers (`output`); fail-open by default |

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
2. 🟡 Agent target with mock tools; indirect prompt injection via tool outputs; canary checks
   (scenario model, mock tools, secondary judges done; agent loop and injection judges not yet)
3. Attack transforms (role-play, encoding, translation) and multi-turn
4. Attacker LLM that refines failed attacks
5. 🟡 LLM judges built (rubric + Llama Guard), labeling + agreement tooling built;
   waiting on ~100 human labels
6. ✅ Defenses (hardened prompt, Llama Guard input/output filters) and the
   security-vs-utility chart; agent-only defenses wait on milestone 2
7. 🟡 Static HTML report, [write-up](docs/WRITEUP.md) and qualitative
   [garak / PyRIT comparison](docs/COMPARISON.md) done; measured head-to-head not run

Design decisions and open questions: [docs/DECISIONS.md](docs/DECISIONS.md).
