# Canary vs garak vs PyRIT

**Status: qualitative comparison, not a benchmark.** Facts about garak and PyRIT were
checked on 2026-10-11 against their repositories (module listings and source files,
cited below), not recalled from memory. No head-to-head run has been done yet; see
[Running a measured comparison](#running-a-measured-comparison).

## What each tool is for

| | Canary | [garak](https://github.com/NVIDIA/garak) | [PyRIT](https://github.com/microsoft/PyRIT) |
|---|---|---|---|
| Purpose | Measure attack success **and** what each defense costs in normal usefulness | LLM vulnerability scanner: "checks if an LLM can be made to fail in a way we don't want" | Framework for security professionals to "proactively identify risks in generative AI systems" |
| Shape | Small config-driven harness (~3.6k lines of source, ~1.9k of tests) | Large scanner: many probes x detectors | Large framework: targets, converters, executors, scorers, memory |
| License | (unset) | Apache-2.0 | MIT |
| Maintainer | one person, portfolio project | NVIDIA + community | Microsoft + community (moved from `Azure/PyRIT`, archived 2026-03-27) |

## Feature comparison

| Capability | Canary | garak | PyRIT |
|---|---|---|---|
| Attack coverage | 1 dataset (JailbreakBench), direct requests only | Many probe modules (DAN, encoding, prompt injection, leak replay, malware gen, ...) | Single- and multi-turn attack executors (`pyrit/executor/attack/{single_turn,multi_turn}`), prompt converters |
| Local models | Ollama (native API) | Ollama generator (`garak/generators/ollama.py`) among ~20 generator modules | OpenAI-style, LiteLLM, HTTP and HuggingFace targets (`pyrit/prompt_target/`); Ollama not checked |
| Rule-based refusal detection | `refusal_patterns` (regex, first 300 chars) | `MitigationBypass` string detector (`garak/detectors/mitigation.py`) | `text_matching` scorer (`pyrit/score/text_matching.py`) |
| LLM-as-judge | Rubric prompt or Llama Guard, as secondary judges | `garak/detectors/judge.py` | LLM scorers (`pyrit/score/llm_scoring.py`, true/false and float-scale) |
| Judge validated against human labels | Blind labeling CLI + agreement (accuracy, precision, recall, Cohen's κ) per judge | Not found in the modules inspected | **Yes**: `scorer_evaluation` evaluates LLM scorers against human-labeled datasets, incl. Krippendorff's α |
| Utility / false refusals | Benign matched prompts; false-refusal rate per defense | Not addressed in the README ("focuses on identifying vulnerabilities") | Not found in the modules inspected |
| Defenses as first-class components | `defenses:` wraps the target (input/output Llama Guard filters; hardened prompt) | A `guardrails` generator module; `shields` detectors read responses from moderation systems (guards, shields, firewalls) | `prompt_shield_target` (Azure Prompt Shields) |
| Security-vs-utility chart | Built in (`canary tradeoff`, HTML report) | No | No |
| Statistics | Wilson 95% CIs on every rate, per category | Pass/fail rates per probe | Not inspected |
| Reproducibility | SQLite response cache keyed on model digest + full request; strict read-only replay; config hash per run | JSONL report log per run | Persistent memory of prompts and scores (`sqlite_memory.py`, `azure_sql_memory.py`) |
| Reporting | Static HTML report (aggregates only), JSON metrics | JSONL log, `garak.log`, hit log of successful attempts | Memory queries and attack analytics modules; a `frontend/` directory exists |

## Where Canary is different (and where it is not)

**Genuinely different**
- **Security and utility in one measurement.** Every defense is run on harmful *and*
  matched benign prompts, so its cost in false refusals is reported next to its
  effect on attack success (R4: a hardened prompt cut ASR 6% -> 1% while false
  refusals went 18% -> 69%). Neither garak nor PyRIT, as inspected, makes this the
  primary output.
- **Judge disagreement is surfaced, not hidden.** All judges run on the same cached
  responses and are reported side by side (R3: three judges, 6% / 0% / 6%, sharing one
  flagged case).
- **Small enough to read.** Every metric (Wilson interval, Cohen's κ, percentiles)
  is implemented in the repo and unit-tested against reference values.

**Not different, credit where due**
- **Validating LLM judges against human labels is not new.** PyRIT's
  `scorer_evaluation` does this, with Krippendorff's α across multiple raters; Canary's
  version is simpler (one rater, Cohen's κ, binary ground truths).
- **Refusal string matching** is the same idea as garak's `MitigationBypass`.

**Where garak and PyRIT are far ahead**
- Attack coverage (probes, converters, multi-turn orchestration), number of
  backends, community, maintenance, and real-world use. Canary's attack side is a
  single dataset of direct requests; milestones 2-4 (agent injection, transforms,
  attacker LLM) are not built.

## Running a measured comparison

Not run yet: garak and PyRIT pull in much heavier dependencies than Canary's three,
and installing them is a choice for the project owner. If done, keep them out of
Canary's environment:

```bash
uvx --from garak garak --target_type ollama --target_name qwen3:4b --probes <probe>
```

A fair comparison would hold the model, prompts and judge fixed and compare (a) the
refusal detectors on the same responses (Canary `refusal_patterns` vs garak
`MitigationBypass` vs PyRIT `text_matching`), scored against the same human labels
with `canary agreement`, and (b) wall-clock and token cost per attack.
