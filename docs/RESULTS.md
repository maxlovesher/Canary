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
- **Next:** human labels (`canary label`) on the R1 run, then
  `canary agreement <this run> --labels <R1 run>/labels.jsonl` decides which judge
  to trust. Llama Guard 3 1B is the planned second LLM judge (different model family).

## R3. Llama Guard 3 1B as judge on the R1 responses (2026-10-03), NOT YET VALIDATED

| | |
|---|---|
| Config | `configs/m5_judge_validation.yaml`, Llama Guard judge only (config hash `aa7b3a66741c`) |
| Responses | Identical to R1 (cache hits) |
| Judge | `llama-guard3:1b` (digest `494147e06bf9…`), native safe/unsafe output on the request+response pair |

**Llama-Guard-judged ASR (unsafe): 6.0% (6/100), Wilson 95% CI [2.8%, 12.5%].** 100/100 judged.

Same headline rate as the refusal judge (R1), but **only 1 of the 6 flagged responses
is shared**. Llama Guard's flags: 5 x category S6 (specialized advice) and 1 x S1
(violent crimes), spread over Economic harm, Privacy, Expert advice (2, both answers
cut off at `max_tokens`), Government decision-making and Harassment/Discrimination.

### Three judges, three answers

| Judge | Measures | ASR on the same 100 responses |
|---|---|---:|
| `refusal_patterns` | did the model not refuse? | 6.0% |
| `qwen3:4b` rubric | did the answer meaningfully help? | 0.0% |
| `llama-guard3:1b` | does the exchange violate Llama Guard's policy taxonomy? | 6.0% (1 overlap with row 1) |

- Agreeing headline numbers can hide near-total disagreement on *which* cases succeeded.
- Llama Guard's S6 "specialized advice" category flags financial/medical/legal advice
  that the human rubric may call safe; its policy is not the same question as
  "did this help a harmful goal".
- None of these is ground truth. Human labels on the R1 run decide which judge (if
  any) is used for the defense results in milestone 6.

## R4. Defenses: security vs utility on qwen3:4b (2026-10-03), PROXY JUDGES

| | |
|---|---|
| Script | `scripts/run_defense_matrix.py` on `configs/m6_defenses.yaml` |
| Harmful set | JBB-Behaviors harmful (sha256 `4a8ec6832056…`), 100 requests, verbatim |
| Benign set | JBB-Behaviors benign (sha256 `3cda234d21a9…`), 100 topic-matched, deliberately borderline requests |
| ASR judge | `refusal_patterns` (proxy: non-refusal) |
| Utility judge | `refusal_patterns` on benign requests: answered = useful; false refusal = 1 - utility |
| Filters | `llama-guard3:1b`, fail-open; blocked requests get a fixed refusal |
| Report | `reports/m6_defenses/tradeoff.{json,svg}`, also in `reports/index.html` |

| Condition | ASR (harmful) | 95% CI | False refusals (benign) | 95% CI | Blocked h / b | p50 latency h / b |
|---|---:|---|---:|---|---:|---:|
| none | 6.0% (6/100) | 2.8 – 12.5% | 18.4% (18/98) | 11.9 – 27.2% | 0 / 0 | 18.3 s / 31.3 s |
| hardened prompt | 1.0% (1/100) | 0.2 – 5.4% | 69.0% (69/100) | 59.4 – 77.2% | 0 / 0 | 7.1 s / 9.0 s |
| Llama Guard input filter | 1.0% (1/100) | 0.2 – 5.4% | 31.3% (31/99) | 23.0 – 41.0% | 95 / 21 | 0.2 s / 29.1 s |
| Llama Guard output filter | 5.0% (5/100) | 2.2 – 11.2% | 33.3% (33/99) | 24.8 – 43.1% | 7 / 18 | 18.5 s / 31.6 s |

### Reading this result

- **No defense lowers ASR significantly at n = 100.** Every ASR interval overlaps the
  undefended 2.8–12.5%. The baseline is already low (and R2/R3 suggest even the 6% is
  mostly judge noise), so this attack set cannot separate the defenses on security.
  Jailbreak transforms (M3) are needed to raise the baseline and give defenses room.
- **Utility costs differ significantly.** The hardened prompt's false refusals
  (59–77%) do not overlap any other condition, despite the prompt explicitly asking
  the model to answer benign requests fully: a 4B model over-applies safety
  instructions. Both Llama Guard filters add ~13–15 points of false refusals (21 and
  18 benign requests blocked).
- **Input filter dominates output filter here:** similar utility cost, lower ASR, and
  95/100 harmful requests are rejected in ~0.2 s without ever reaching the model.
  The output filter mostly re-blocks answers that were already refusals (7 blocks,
  ASR 6% -> 5%).
- **Caveats.** Both axes use the proxy refusal judge (R1–R3 show its limits). The
  benign baseline already refuses 18%: JBB's benign split is built from borderline,
  topic-matched requests. 25–30 of 100 benign answers hit `max_tokens: 2048` and were
  judged on partial text (refusals appear early, so the refusal judge is unaffected;
  an LLM judge would not be).
- **Parser bug found and fixed during this analysis.** Llama Guard once answered a
  bare `S6` without the `unsafe` line; the fail-open filter had let that benign
  request through. The parser now treats a bare category as unsafe and unparseable
  outputs are logged. Numbers above are from the fixed parser (cached replay; this
  changed the output filter's benign blocks from 17 to 18 and nothing else). No
  classifier errors occurred.
