# Reliability levers for local SWE-bench agents — research memo

**Date:** 2026-07-26
**Scope:** feeds the Phase-2 (best-of-N) design decision for `spark-swe-eval` (see
`docs/design.md`). Grounds the observed Phase-1
result (`docs/report.md`: `infinity-high` 33.3% vs `infinity-low` 66.7% on N=3) in the broader
literature.

**Method note:** Perplexity MCP (`mcp__perplexity__search`/`reason`) is not registered in this
environment — `ToolSearch` returned no match. Used `WebSearch`/`WebFetch` instead, tracing every
load-bearing number to a fetched page or search result. Confidence tags per claim:
**[confirmed]** = read directly off a fetched primary source; **[reported]** = from a search
snippet/secondary source I could not fully re-verify by direct fetch; **[inference]** = my
synthesis, not a direct claim from any source.

---

## 1. Best-of-N / sampling + selection

**Sampling + selection helps, substantially, and the size of the win is well quantified:**

- SWE-Gym (OpenHands + Qwen2.5-Coder-32B-Instruct, SWE-bench Verified) **[confirmed, direct fetch]**:
  - N=1 baseline: **20.6%**
  - Oracle `pass@k` (upper bound — a candidate is correct if *any* of k samples resolves): **37.8% at k=8**. This is the ceiling selection could reach.
  - Practical selection via a **trained verifier/reward model** (no ground truth, ORM scores candidates): **Best@8 = 29.8%** (+9.2pp), **Best@16 = 32.0%** (+11.4pp).
  - Moatless + 32B on Lite: 19.7% → 26.3% with the same verifier at k=8.
  - Source: [Training Software Engineering Agents and Verifiers with SWE-Gym](https://arxiv.org/html/2412.21139) (arXiv 2412.21139).
- SWE-RL (Llama3-SWE-RL-70B, Verified) **[reported, cross-checked across 2 independent snippets]**:
  - Greedy (N=1) SFT baseline: 29.6%; RL-trained greedy (N=1): 34.8%.
  - Best@160: **40.0%**; Best@500: **41.0%** — only **+1pp for 3.1x more samples**, a clean diminishing-returns curve past ~N=160.
  - Selection method: regression-test filtering (keep top-5-by-majority tests per instance, execute remaining patches against the filtered novel-test set, pick highest pass rate; ties broken by majority patch, then by shorter trajectory).
  - Source: [SWE-RL](https://arxiv.org/pdf/2502.18449) (arXiv 2502.18449); numbers cross-checked via [AK/X post](https://x.com/_akhaliq/status/1894584315352076608) and a Threads repost.
- Agentless (localize → repair → validate) **[confirmed for method, reported for numbers]**: samples multiple candidate diffs, filters by **syntax check + regression test execution**, then **majority-votes** among survivors after normalizing patches to strip cosmetic diffs. 32.00% on SWE-bench Lite (96/300, $0.70/instance) at original publication; >50% on Verified with Claude 3.5 Sonnet (40.7% Lite / 50.8% Verified, Dec-2024 update). Source: [Agentless paper](https://arxiv.org/abs/2407.01489), [GitHub](https://github.com/OpenAutoCoder/Agentless).
- **Contrarian data point:** TRAE (75.2% on Verified) reportedly *dropped* majority voting after observing performance **decline** as the sampling space grew — naive majority vote doesn't monotonically improve with N, especially without execution filtering first. **[reported]**

### How to select without ground-truth tests (ranked by evidence strength)

1. **Regression/execution filtering against the repo's own pre-existing tests, or an agent-generated reproduction test for the issue** (Agentless/SWE-RL recipe). Strongest, most consistently reported. Does not require the held-out `test_patch` — only the repo's existing suite (or a subset) and/or a test the model itself writes to reproduce the bug.
2. **Majority vote over normalized patches**, used as a *tie-breaker after* execution filtering, not standalone — standalone majority vote can plateau or regress at high N (TRAE).
3. **Learned verifier / reward model** (SWE-Gym ORM) — real gains (+9–11pp) but leaves a visible gap to the oracle ceiling (29.8–32.0% vs 37.8% oracle at k=8), and requires training a verifier model — not a fit for "just wire up the existing grader."
4. **Generic LLM-as-judge** (untrained, just prompting an LLM with the candidate diffs) — weakest evidence in what I found; Augment Agent's approach (prompting o1 with a list of diffs to majority-vote) is the only concrete example surfaced, and it's functionally closer to (2) than to a real judge.

### Which wins in practice, and N sizing

**Execution-based filtering (regression tests / reproduction tests) beats pure majority voting**, and majority voting is best used only as a tie-breaker among execution survivors. **N marginal return**: most of the achievable gain shows up by **N≈8–16** (SWE-Gym: 20.6→29.8→32.0 at k=8,16; oracle 20.6→37.8 at k=8); pushing N from ~160→500 buys only ~1pp (SWE-RL). For a compute-constrained single-box setup, **N=5–8 is the practical sweet spot** — beyond that you're mostly burning GPU-host cycles for fractions of a point.

**Scope note specific to this project:** your own Phase-2 design ("select by the Phase-1 test runner") plans to select using the *actual* grader, which applies `test_patch` and runs the real `FAIL_TO_PASS`/`PASS_TO_PASS` tests. That is a valid **oracle-`pass@k` ceiling measurement** (tells you how much of the gap is "generation" vs "selection"), but it is *not* the no-ground-truth production method — in a real deployment you wouldn't have the held-out test. Worth stating explicitly in the Phase-2 writeup so the number isn't later read as a deployable pass@1.

---

## 2. Agent scaffold

No single source gave a clean same-model, same-scaffold matrix across SWE-agent/OpenHands/Agentless/Moatless/Aider for one open model — leaderboard entries mix model + scaffold + sampling budget. Numbers found **[reported unless noted]**:

| Scaffold | Model | SWE-bench Verified pass@1 | Note |
|---|---|---|---|
| OpenHands + CodeAct v2.1 | Claude 3.5 Sonnet | 53.0% | best documented open-source **scaffold** result, but with a frontier model, not open-weight |
| OpenHands | Qwen2.5-Coder-32B (SWE-Gym fine-tuned) | 20.6% (N=1) | **[confirmed]**, direct fetch |
| OpenHands | Devstral-Small-24B | **46.8%** | Mistral's own number, "same scaffold" claim: beats DeepSeek-V3-0324 (671B) and Qwen3-232B-A22B under identical OpenHands scaffold |
| Agentless | Claude 3.5 Sonnet | 40.7% Lite / 50.8% Verified | |
| Agentless (orig., GPT-4-class) | — | 32.0% Lite ($0.70/instance) | original paper baseline |
| Moatless | Claude 3.5 Sonnet | 39% ($0.14/instance) | |
| Moatless | Claude Haiku 4.5 | 35.9% | |
| Moatless | DeepSeek V3 | 30.7% | |
| Moatless | Llama 4 Maverick | 14.7% | cited as "best fully self-hosted open-weight option" as of that source |
| SWE-RL / Agentless-style RL training | Llama3-SWE-RL-70B | 34.8% (N=1) / 41.0% (Best@500) | **[reported, cross-checked]** |
| No scaffold given (self-reported) | Qwen3-Coder-480B-A35B | 66.5–69.6% | Qwen's own number, "without test-time scaling" per one source — scaffold not specified, treat as vendor-optimistic |
| — | Qwen3-Coder-30B (your `nova` tier) | ~50.0% | one source's number for the 30B specialist variant, scaffold unspecified — **could not verify independently**, flag as low-confidence |

**Does a simpler pipeline (Agentless-style) beat a full agent for weaker models?** The evidence is directional, not a clean controlled comparison: Agentless's own framing is explicitly that a streamlined localize→repair→validate pipeline **recovers most of the oracle gap at much lower cost** than a full ReAct-style agent, and its "no autonomous action-selection" design removes a failure mode (the agent choosing bad next actions / looping) that hurts weaker models specifically. One survey-style source phrased it as "a simple pipeline with strong localization and validation can beat a more ornate agent if it recovers the oracle gap with less cost." **[reported, moderate confidence]** — I could not find a same-model, same-N head-to-head (e.g., qwen3-coder:30b under Agentless vs under a ReAct agent) to give you a number. Given your scope guard ("no new agent scaffold" for Phase 1), this is a **Phase-3-or-later consideration**, not urgent.

---

## 3. Reasoning effort under a time/step budget

This directly explains your Phase-1 observation. Two findings, and they are not in conflict — they're about *different conditions*:

1. **Under an unconstrained/generous budget, higher reasoning effort helps a lot.** The gpt-oss-120b/20b model card's own ablation table, on their internal (presumably budget-generous) harness **[confirmed, direct fetch of arXiv 2508.10925]**:
   - SWE-bench Verified, gpt-oss-120b: **low 47.9% → medium 52.6% → high 62.4%**.
   - Codeforces Elo (with tools): low 1653 → medium 2365 → high 2622.
   - The card explicitly says CoT length scales with reasoning level and gives "log-linear returns... at a relatively large increase in final response latency and cost" — i.e., it costs more time, but on an unbounded budget it's a net win.

2. **Under a tight step/wall-clock budget, high reasoning effort is a documented failure mode — the model reasons instead of acting, and can burn the whole budget before emitting a tool call/diff.** Evidence:
   - GitHub issue: "[Bug] GPT OSS 120B subagent stops mid-reasoning and returns empty result after several tool calls" — the model executes tool calls correctly for a while, then a subsequent reasoning step aborts and returns nothing to the caller. **[confirmed, direct fetch]** — [opencode issue #27210](https://github.com/anomalyco/opencode/issues/27210).
   - The model card itself documents an **"overthinking" problem**: gpt-oss-20b/120b "spend more tokens to reason on questions they eventually get incorrect." **[confirmed]**
   - SMART (arXiv 2502.11435): "excessive reasoning before tool-calling can decrease open-source agent performance... minimal reasoning with frequent tool calls outperforms extensive self-reasoning" for complex domain tasks. **[reported]**
   - General test-time-scaling literature: "excessively large static reasoning budgets lead to diminishing returns, with performance dropping beyond a certain point" and agents show "rapidly diminishing returns with increased compute." **[reported]**, e.g. [Timely Machine](https://arxiv.org/html/2601.16486), [Inference-Time Budget Control for LLM Search Agents](https://arxiv.org/pdf/2605.05701).

**Synthesis [inference, but directly consistent with your own Phase-1 data]:** this is a known, named failure mode, not noise — reasoning=high is a genuine accuracy lever *given enough turns/wall-clock to also act on the reasoning*, but under a fixed wall-clock cap (your 20-min budget) it competes with the agent's own action budget: more tokens spent thinking is fewer tool-call turns fit into the same clock, and ollama-served gpt-oss is specifically reported to sometimes abort mid-CoT and return empty rather than degrade gracefully. Your result (`infinity-high` produced no patch on 2/3 instances) matches this pattern exactly rather than being an anomaly.

**What to set:** no source gives a single blanket recommendation for "agentic coding, tight budget" beyond the general pattern — but the consistent shape across sources is: default to **low or medium** reasoning effort when the harness enforces a hard wall-clock/step cap, and reserve **high** for either (a) generous/unbounded budgets, or (b) an adaptive scheme (start low, escalate to high only on a stuck/retry turn, not from turn 1). Given you already run `infinity-low`/`infinity-high` as separate arms, the cleanest next experiment is **`infinity-medium`** to locate where the crossover happens for your specific 20-min cap.

---

## 4. Cheap reliability wins

Ranked by (impact × ease) for a crush→ollama pipeline that can already sample N and grade by execution:

- **Retry-on-test-failure / self-repair loop** — feed the agent its own failing test/grader output and let it retry. Reflexion: **+11%** on Python programming tasks, **+22%/12 iterative steps** on AlfWorld, via verbal self-reflection (no gradient update, just re-prompting with the failure). **[reported]** ([Reflexion](https://openreview.net/pdf?id=vAElhFcKW6)). Separately, "How Many Tries Does It Take? Iterative Self-Repair..." (arXiv 2604.10508) reports **smaller/weaker models gain more from retry than larger models** (larger models already get it right more often on try 1), and that **most of the gain concentrates in the first 2–4 retries**, with returns flattening past 4–5. **[reported, direct-fetch attempted but PDF extraction was partial]**. This is squarely relevant to your 30B/80B local tier.
- **Regression-test filtering as a Best-of-N selector** — see §1. Biggest single quantified lever (Agentless doubling scores; SWE-Gym +9–11pp). Needs the grader to run on each of N candidates instead of one — you already have `grader.py`; this is orchestration, not new capability.
- **Patch/diff format enforcement** — Aider's own ablation on GPT-4 Turbo, **[confirmed, direct fetch]**: switching from SEARCH/REPLACE to unified-diff format cut "lazy"/incomplete edits from 80% of tasks down to ~39% (20%→61% "non-lazy" score on an 89-task refactor benchmark) — roughly a **3x reduction in incomplete-edit failures**. Whole-file rewrite was reported elsewhere as "more stable overall" across single- and multi-turn settings, at the cost of needing bigger context. For a weaker local model, cheap and safe: enforce a strict, narrow diff/patch grammar with a fuzzy-match fallback (don't require exact line numbers), or fall back to whole-file rewrite for small files.
- **Temperature/top-p** — T=0 is standard for a single deterministic pass@1 attempt and is what the official SWE-bench harness historically defaulted to. **[reported]** ([On Randomness in Agentic Evals](https://arxiv.org/pdf/2602.07150)). It only becomes a lever once you sample N>1: the self-consistency literature's empirical sweet spot is **T≈0.5–0.7 at N=5–20** — low T maximizes pass@1 per sample, higher T maximizes diversity/pass@k. **[reported]** Trivial to integrate (it's a request parameter), but it only pays off paired with Best-of-N.
- **Self-consistency / majority vote alone** — cheapest to integrate (no test execution needed), but weakest standalone evidence — TRAE's regression at high N is a warning sign. Use only as a tie-breaker layered on top of execution filtering, not a replacement for it.
- **LLM-judge selection** — least-evidenced, most integration cost (extra full-context LLM call per pair/set of candidates, judge-selection bias risk). Skip unless execution-based selection is unavailable for some candidates.

**Caveat that applies to all execution-based methods:** "Are 'Solved Issues' in SWE-bench Really Solved Correctly?" (arXiv 2503.15223) found that passing tests (including `FAIL_TO_PASS`+`PASS_TO_PASS`) doesn't guarantee the patch matches developer intent — tests are rarely exhaustive. This doesn't invalidate test-execution selection (it's still the strongest signal available), but it means "resolved" per your grader is a proxy, not proof of correctness — consistent with the "small-N, subset caveat" discipline your own design doc already applies.

---

## 5. The one thing to implement first

**Best-of-N sampling (start N=5–8) with regression/execution-based selection, reusing the grader you already built — not a new self-repair loop, not a learned verifier, not an LLM judge.**

Why this over the alternatives:

- It is **already your own Phase-2 scope** ("sample N agent runs, select by the Phase-1 test runner") — no new design needed, just build it.
- It has the **strongest, most consistently reported quantified effect** of everything surveyed: SWE-Gym +9–11pp over N=1 baseline at N=8–16 with only a learned proxy verifier; Agentless-style execution filtering roughly doubles resolve rate over naive single-sample generation in the papers that report it. Your test-execution grader is a *stronger* selection signal than the learned verifiers those papers used, so you should capture more of the oracle-`pass@k` gap than they did.
- It requires **zero new agent-side capability** — `agent_run.py` already produces one patch per run; running it N times independently and picking the best via `grader.py` is orchestration, not a scaffold change, and doesn't violate the Phase-1 "no new agent scaffold" scope guard.
- Pair it with two near-zero-cost adjustments while you're in there: (a) drop `reasoning_effort` to **low or medium** for the N sampled runs given the §3 finding — high reasoning effort under your wall-clock cap is actively costing you resolved instances, not just latency; (b) set temperature to the ~0.5–0.7 range for the N>1 samples so they're not N copies of the same greedy trajectory.

Self-repair/retry-on-failure is the natural **second** lever — genuinely well-evidenced and likely to help your weaker local tiers most — but it requires deeper changes to how the agent's `run` command consumes mid-session feedback, which is more invasive than "run it N times and grade each." Sequence it after Best-of-N lands.

---

## Sources

- [Agentless: Demystifying LLM-based Software Engineering Agents](https://arxiv.org/abs/2407.01489) (arXiv 2407.01489) + [GitHub](https://github.com/OpenAutoCoder/Agentless)
- [Training Software Engineering Agents and Verifiers with SWE-Gym](https://arxiv.org/html/2412.21139) (arXiv 2412.21139)
- [SWE-RL: Advancing LLM Reasoning via Reinforcement Learning on Open Software Evolution](https://arxiv.org/pdf/2502.18449) (arXiv 2502.18449); cross-check via [AK/X post](https://x.com/_akhaliq/status/1894584315352076608)
- [Dissecting the SWE-Bench Leaderboards](https://arxiv.org/pdf/2506.17208) (arXiv 2506.17208) — referenced for majority-voting/TRAE context; full-text PDF extraction was only partially successful
- [gpt-oss-120b & gpt-oss-20b Model Card](https://arxiv.org/html/2508.10925v1) (arXiv 2508.10925)
- [opencode issue #27210 — GPT OSS 120B subagent stops mid-reasoning, returns empty result](https://github.com/anomalyco/opencode/issues/27210)
- [SMART: Self-Aware Agent for Tool Overuse Mitigation](https://arxiv.org/pdf/2502.11435) (arXiv 2502.11435)
- [Timely Machine: Awareness of Time Makes Test-Time Scaling Agentic](https://arxiv.org/html/2601.16486) (arXiv 2601.16486)
- [Inference-Time Budget Control for LLM Search Agents](https://arxiv.org/pdf/2605.05701) (arXiv 2605.05701)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://openreview.net/pdf?id=vAElhFcKW6)
- [How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation Across Model Scales and Benchmarks](https://arxiv.org/pdf/2604.10508) (arXiv 2604.10508)
- [Aider: Unified diffs make GPT-4 Turbo 3X less lazy](https://aider.chat/docs/unified-diffs.html)
- [On Randomness in Agentic Evals](https://arxiv.org/pdf/2602.07150) (arXiv 2602.07150)
- [Are "Solved Issues" in SWE-bench Really Solved Correctly? An Empirical Study](https://arxiv.org/html/2503.15223v1) (arXiv 2503.15223)
- Devstral: [Mistral AI announcement](https://mistral.ai/news/devstral/), [Ollama library](https://ollama.com/library/devstral:24b), [VentureBeat coverage](https://venturebeat.com/ai/mistral-ai-launches-devstral-powerful-new-open-source-swe-agent-model-that-runs-on-laptops)
- Moatless numbers: [Coding Agents — Open Source Approaches on SWE-Bench](https://medium.com/@te2be/coding-agents-open-source-approaches-on-swe-bench-074cc28c5bb0)
- Qwen3-Coder self-reported numbers: [Qwen3-Coder blog](https://qwenlm.github.io/blog/qwen3-coder/)
- [SWE-bench Verified — OpenAI announcement](https://openai.com/index/introducing-swe-bench-verified/)

**Not used (attempted, could not verify):** a set of "best@16 = 65.8%", "best@40 = 80.4%" figures surfaced in one WebSearch synthesis without a traceable primary source — excluded from this memo per the no-training-data-only rule.

---

## Recommended levers, ranked

| Lever | Expected pass@1 impact | Integration effort | Evidence strength |
|---|---|---|---|
| Best-of-N (N=5–8) + regression/execution-based selection via existing grader | High (+9–20pp range across sources; likely toward the high end since our selector is real test execution, not a learned proxy) | Low (orchestration only — reuses `agent_run.py` + `grader.py` as-is) | Strong — SWE-Gym, SWE-RL, Agentless all quantify this directly |
| Drop `reasoning_effort` to low/medium for wall-clock-capped runs | Medium-high (Phase-1 already measured -33.3pp for high vs low on N=3; model card shows the opposite direction on unconstrained budgets, confirming the budget interaction) | Trivial (config flag) | Strong — matches our own Phase-1 data + documented gpt-oss overthinking/empty-output bug |
| Retry-on-test-failure / self-repair loop (feed grader output back, 2–4 retries) | Medium-high (+11 to +22pp reported on other domains; disproportionately helps smaller/weaker models per iterative-repair study) | Medium (needs `agent_run.py` to support mid-session feedback injection) | Medium — strong effect sizes reported, but not SWE-bench-specific numbers found |
| Patch/diff format enforcement + fuzzy-match fallback | Medium (~3x fewer incomplete-edit failures in Aider's ablation) | Low (prompt template + parser tolerance) | Medium — one strong ablation (GPT-4 only), directionally plausible for weaker models |
| Temperature ≈0.5–0.7 for the N sampled runs (T=0 for single-shot baseline) | Low-medium on its own; multiplies the Best-of-N gain | Trivial (request parameter) | Medium — general self-consistency literature, not SWE-bench-specific |
| Majority vote on normalized patches, as tie-breaker only | Low-medium, and only after execution filtering | Low | Mixed — helps in some pipelines (Agentless), reported to regress standalone at high N (TRAE) |
| Learned verifier / reward model | Medium (+9–11pp per SWE-Gym) but leaves a gap to oracle | High (requires training/fine-tuning a verifier) | Strong evidence, poor fit for "reuse what we have" |
| Generic LLM-as-judge selection | Low-uncertain | Medium-high (extra LLM call, judge bias risk) | Weak — least-evidenced option surveyed |
