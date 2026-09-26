# spark-swe-eval — reliability report (2026-07-26)

Goal: *get the harness working properly, and research + implement levers for more reliable agent
solutions.* This documents what was broken, what was fixed, and what the levers buy.

## 1. The real reliability hole was the grader host, not N=3

Phase 1 graded on a separate x86 desktop. Re-running an expanded gold/empty gate on it with
`max_workers=4`, that host **went offline mid-run** (Tailscale reported it "offline, last seen
5m ago") — almost certainly OOM/crash under four parallel heavy Docker builds (sympy/xarray/sphinx
images are large). It did not come back within the session (needs a power cycle). It is a sleep-
and dual-boot-prone desktop; as the *sole* grader it is a single point of failure. A batched grader
that loses the whole run when the host dies compounds it.

## 2. Fix: grade on the always-on arm64 agent host itself via emulation

swebench 4.1.0's CLI hardcodes `arch="x86_64"` (in `make_test_spec()`) and builds
`FROM --platform=linux/x86_64` — its prebuilt images cannot run natively on the aarch64 agent host
(`exec format error`). Two routes exist; **qemu binfmt emulation** is the reliable, zero-code one:

```
docker run --privileged --rm tonistiigi/binfmt --install amd64   # register x86 emulation once
```

The stock harness + prebuilt x86 images then run under emulation. **Verified:** gold
`django__django-11099` grades **RESOLVED** on the arm64 host (test phase ~122 s; the big wall-clock
is the one-time x86 image pull, ~40 min for the first django image — env images cache afterward).
Validated end-to-end through our own harness: `run_grader(host=GRADER_HOST, workdir="~/swe-grade-arm",
max_workers=1)` → **gold p@1 = 1.0, empty p@1 = 0.0** (the validation gate passes on the arm64 host).

Consequence: **the arm64 agent host is now a self-contained agent + grader; the x86 desktop is no
longer required.** Keep `max_workers=1–2` on it — parallel *emulated* Docker builds are heavy and
are exactly what overloaded the x86 host. (A native-arm64 build path exists in swebench but is
unreachable without patching `make_test_spec(arch="arm64")`; it's the faster-but-riskier fallback.
Emulation is the default.)

## 3. Research: which levers actually raise open-model pass@1

Full memo: `docs/research-reliability.md`. Headlines (sourced):
- **Best-of-N + execution/regression-based selection** is the strongest, best-evidenced lever
  (SWE-Gym: 20.6% → 32% at Best@8; Agentless/SWE-RL gain from regression-test filtering + majority
  vote, *no ground truth*). Sweet spot **N = 5–8**.
- **reasoning=high is a documented double-edged sword.** Unconstrained it *helps* (gpt-oss SWE-bench
  Verified 47.9% → 62.4% low→high); under a tight wall-clock/step budget it *backfires*
  ("overthinking" → empty output). Phase 1's −33 pp for Infinity-high is the budget-limited side.
- **Honesty rule:** selecting the candidate by the held-out `FAIL_TO_PASS` test is an **oracle
  pass@k ceiling**, not a deployable result. We report both, labeled.

## 4. What was built (37 tests, ruff + format clean)

- **`bestofn.py`** — non-leaky majority-vote selector over normalized diffs (`cluster_key` ignores
  hunk position / index hashes / context), `aggregate_instance` → oracle vs deployable. Never sees
  test results.
- **`phase2.run_bestofn`** — sample N, grade every candidate, report oracle pass@k + deployable
  pass@1. I/O injected → unit-tested without hardware.
- **`agent.sample_patches`** — N independent samples/instance (crush has no temperature flag; relies
  on default sampling stochasticity).
- **`agent.build_agent_script(scaffold=…)`** — selectable `bare` (baseline, unchanged) vs `guided`
  (reproduce → fix → verify → iterate; execution-feedback, **never leaks FAIL_TO_PASS**), so the
  scaffold can be A/B'd instead of silently shifting the baseline.
- **`grade.run_grader`** — now parameterized `max_workers` + `workdir` (for the low-load arm64
  grader), ssh timeout raised to 4 h; `cli bestofn` subcommand wires it all.

Bugs fixed en route: the x86-host crash exposed that batched grading loses everything on a host
death (→ keep max_workers low; per-instance resumability is the next hardening step); and `cli.py`
lacked a `__main__` guard, so `python -m spark_swe_eval.cli` silently no-op'd (exit 0, no output) —
fixed.

## 5. Best-of-N result (Nova 30B, N=5) — the lever has headroom; the *selector* is the bottleneck

Full pipeline on real hardware: Nova (qwen3-coder:30b) agent on the arm64 host, 5 independent
samples per instance, every candidate graded on that same host's emulated grader. Rate over the
**N=13** validated subset (`subset-v2.txt`), 5 repos:

| metric | value | |
|---|---|---|
| single-shot pass@1 | **41.5%** | 27 / 65 (instance,sample) pairs resolve |
| best-of-N deployable (majority-vote) | **46.2%** | 6 / 13 instances |
| **oracle pass@k ceiling** | **61.5%** | 8 / 13 instances |

Per-instance (resolved of 5):
```
django-11099 4  flask-5014 3  django-16082 4  django-16429 4  pylint-6903 4  pytest-6202 4  → majority resolves, selector wins (6)
requests-1921 3  pytest-5262 1                                                              → resolver EXISTS but selector MISSES (2)
pylint-7080 0  django-13406 0  requests-6028 0  requests-5414 0  pylint-4970 0              → capability gap, 0/5 (5)
```

**The honest headline: best-of-N has real headroom, but majority-vote captures almost none of it.**
- **Oracle ceiling 61.5% vs single-shot 41.5% = +20 pp** of reachable headroom.
- **Majority-vote deployable 46.2%** captured only **+4.7 pp** of that — a **15.3 pp gap** left on the table.
- **The decisive case, requests-1921:** *3 of 5 samples resolved* (a majority resolved!) yet majority-vote
  still missed it — the 3 correct fixes were *diverse* diffs while the 2 failures were *identical*, so
  diff-clustering picked the wrong cluster. A resolved-rate-unaware selector fails **even when the
  majority is correct**. This is the clinching argument for **execution/regression-based selection**
  (run the repo's PASS_TO_PASS + a reproduction, reject regressions) — the highest-value next lever, and
  the harness now *measures* its value directly (oracle − deployable). Matches the research (majority
  vote "regressed at high N" for TRAE).
- **5/13 are capability gaps** (0/5) — best-of-N can't help when no sample ever resolves (pylint is
  consistently hard for these models; cf. pylint-7080 in Phase 1).

*(A 6-instance run earlier read single 66.7% / oracle 83.3% / deployable 66.7%; the N=13 numbers are
lower because the larger subset includes harder instances. Per-candidate results also vary run-to-run —
stochastic sampling, no temperature control — so treat these as point estimates without CIs.)*

## 6. Honest limitations

- Rate is N=5 on 6 instances (1 per repo), no CIs yet; 3 of the 6 are near-saturated single-shot, so
  the informative instances are few. Bigger N-instances needed for a tight number.
- Emulated grading is correct but slow (one-time image pulls); fine for a curated subset, not the full 500.
- The reasoning=high question still needs a clean re-run at a *longer* agent budget to separate
  "overthinking" from "not enough time to act."
- Best-of-N diversity relies on default sampling stochasticity (crush has no temperature flag); an
  explicit temperature ~0.5–0.7 (set in crush.json) would likely widen candidate diversity.

## 7. Next (highest-value first)

1. **Execution/regression-based selector — the measured bottleneck.** The 6-instance run shows a
   **16.7 pp gap** between the oracle ceiling (83.3%) and the majority-vote deployable result (66.7%):
   real headroom the naive selector throws away. Replace/augment majority-vote with: apply each
   candidate in the grader env, run the repo's own **PASS_TO_PASS** tests, reject regressions/non-applies,
   and prefer candidates that pass an agent-written reproduction. This is the single highest-value lever
   and directly captures that 16.7 pp. (Selection must still never touch FAIL_TO_PASS.)
2. **Best-of-N at larger N-instances — DONE** (N=13 above). Still no CIs and no temperature control;
   a bootstrap CI + a temperature ~0.6 sampling sweep would sharpen the rate and widen candidate diversity.
3. **Guided vs bare scaffold A/B** — the `guided` (reproduce→verify) scaffold is built and non-leaky;
   run it head-to-head with `bare` on Nova to measure the execution-feedback lift.
4. **reasoning=high re-run at a longer budget** — settle whether Phase 1's −33 pp is "overthinking"
   or just "ran out of time to edit."
5. **Grader hardening** — make `run_grader` per-instance + resumable so a host death never loses a
   whole batch (the failure mode the x86-host crash exposed).
