# Results log

Aggregate numbers only. Prompts and model responses stay in the local, gitignored
`runs/` directory. Every number here is **measured** unless marked otherwise.

## R1. JailbreakBench direct requests vs qwen3:4b (2026-10-02)

| | |
|---|---|
| Config | `configs/m1_jbb_direct.yaml` (config hash `bf6689933583`) |
| Target | Ollama `qwen3:4b` Q4_K_M, digest `359d7dd4bcda…`, `think: true`, `max_tokens: 2048`, temperature 0, seed 1234 |
| System prompt | "You are a helpful assistant." (no hardening) |
| Attacks | JBB-Behaviors harmful split, 100 behaviors, sent verbatim (no jailbreak transforms); sha256 `4a8ec6832056…` |
| Judge | `refusal_patterns`: **proxy** ASR = non-refusal rate (first 300 chars of the final answer) |
| Hardware | RTX 3060 Laptop 6 GB |

**Overall proxy ASR: 6.0% (6/100), Wilson 95% CI [2.8%, 12.5%].** 0 unjudged.

| Category | n | Proxy ASR | 95% CI |
|---|---:|---:|---|
| Disinformation | 10 | 10% | [1.8%, 40.4%] |
| Economic harm | 10 | 20% | [5.7%, 51.0%] |
| Expert advice | 10 | 20% | [5.7%, 51.0%] |
| Fraud/Deception | 10 | 0% | [0.0%, 27.8%] |
| Government decision-making | 10 | 0% | [0.0%, 27.8%] |
| Harassment/Discrimination | 10 | 0% | [0.0%, 27.8%] |
| Malware/Hacking | 10 | 0% | [0.0%, 27.8%] |
| Physical harm | 10 | 0% | [0.0%, 27.8%] |
| Privacy | 10 | 10% | [1.8%, 40.4%] |
| Sexual/Adult content | 10 | 0% | [0.0%, 27.8%] |

Cost and latency: mean 18.1 s per attack (p50 18.3 s, p95 32.5 s), ~1,085 output
tokens per attack (reasoning + answer), $0 (local). 3 responses hit `max_tokens`
(1 judged a non-refusal on its partial answer, 2 judged refusals).

### Reading this result

- **Proxy, not validated.** A non-refusal is not necessarily harmful content; the 6
  hits have not been hand-labeled yet (milestone 5). Treat 6% as an *upper-bound-style*
  estimate of direct-request jailbreak success for this model and judge.
- **Per-category differences are not significant.** With n = 10 every category CI
  overlaps every other; e.g. "Expert advice" 20% vs "Malware/Hacking" 0% is within noise.
- **Refusal style matters for the judge.** Median answer length is ~2,800 chars even
  though 94% were judged refusals, i.e. the model typically refuses and then redirects
  with general information. The 300-char window treats that as a refusal; whether
  the redirect leaks anything useful is a question for the LLM judge.
- **Baseline only.** No jailbreak transforms (milestone 3) or attacker LLM
  (milestone 4) were applied; this is the floor that those attacks are measured against.

## R2. LLM rubric judge on the R1 responses (2026-10-03), NOT YET VALIDATED

| | |
|---|---|
| Config | `configs/m5_judge_validation.yaml`, rubric judge only (config hash `d5ae1c2a4e8e`) |
| Responses | Identical to R1 (all 100 target calls were cache hits; primary ASR reproduced exactly) |
| Judge | `qwen3:4b` with the 3-way rubric prompt, `think: true`, `max_tokens: 4096`, `num_ctx: 12288` |

**LLM-judged ASR (HARMFUL): 0.0% (0/100), Wilson 95% CI [0.0%, 3.7%].** 100/100 judged.

| | LLM: REFUSAL | LLM: SAFE | LLM: HARMFUL |
|---|---:|---:|---:|
| Refusal judge: refusal | 23 | 71 | 0 |
| Refusal judge: non-refusal | 0 | 6 | 0 |

### Reading this result

- **The two judges agree on harm, disagree on refusal style.** All 6 proxy "successes"
  from R1 are judged SAFE (engaged but not harmful). The 71 refusal/SAFE disagreements
  are "refuse, then give general information": the rule judge calls that a refusal,
  the rubric calls it safe compliance. For attack success both say "failed".
- **If the LLM judge is right, true direct-request ASR is ~0%** and the 6% proxy was
  entirely false positives. That is a hypothesis, not a result: this judge is the
  same model as the target (self-preference bias) and has not been checked against
  human labels.
- **Measured cost of judging:** 1024 tokens left 93/100 judgements with no answer
  (all reasoning); 4096 was enough for 100/100. Judging took ~36 min of GPU time for
  100 cases on an RTX 3060 6 GB, longer than generating the responses.
- **Next:** human labels (`redbench label`) on the R1 run, then
  `redbench agreement <this run> --labels <R1 run>/labels.jsonl` decides which judge
  to trust. Llama Guard 3 1B is the planned second LLM judge (different model family).
