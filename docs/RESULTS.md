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
