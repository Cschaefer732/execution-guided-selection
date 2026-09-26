# spark-swe-eval — Design

**Date:** 2026-07-23
**Status:** Design, pre-implementation
**Host (agent):** an arm64 GPU host with large unified memory (`$AGENT_HOST`), running a
local-model coding agent (private harness, built on Crush → ollama)

---

## 0. Scope: this is Phase 1 of a 3-phase program

The goal of the program is to close the *effective* coding-accuracy gap between our local
coding agent and a frontier model, and — first — to **measure it honestly on our own harness**
instead of quoting vendor benchmark numbers.

| Phase | Deliverable | Depends on |
|---|---|---|
| **1 (this spec)** | An eval harness that scores the agent's *real* pass@1 on a SWE-bench Verified subset, by test execution | — |
| 2 | Best-of-N: sample N agent runs, select by the Phase-1 test runner | Phase 1 harness |
| 3 | Escalate-to-frontier: local-first, escalate test-failing tasks to a frontier API; measure pass@1 + cost | Phases 1–2 |

Phases 2 and 3 are **out of scope here** — their design depends on Phase-1 numbers (if local
pass@1 is already high, best-of-N matters less; the escalation threshold is set from the measured
failure distribution). This spec builds only the instrument. It is deliberately reusable: the
Phase-1 test runner *is* the Phase-2 selector and the Phase-3 escalation trigger.

---

## 1. What this is

A measurement harness. It runs coding tasks through the **actual** agent (Crush + our configured
model + our system prompt + reasoning setting) and grades each result by **running the task's
tests** — a task either makes its `FAIL_TO_PASS` tests pass or it does not. No LLM judge, no judge
noise.

The research framing (from prior research this session): on an *identical* harness (Scale
SWE-bench Pro) frontier models beat open-weight ones by 10–40 pp, and separately, *harness*
choice swings the same model 5–36 pp. Vendor numbers for our driver-class arm were produced on a
reference harness that is **not ours**. This project produces the number that is ours.

**Headline output:** pass@1 for each model arm on the same subset, same scaffold, with cost, plus
the answer to a concrete open question — *did setting `reasoning_effort=high` on our large MoE
arm actually raise resolution rate, or only latency?*

---

## 2. The binding constraint: arm64 grading

SWE-bench Verified's official evaluation uses **per-instance Docker images that are x86_64**.
The agent host is arm64. Running x86 images under qemu emulation is slow and unreliable; not every
instance environment has an arm64-native build. This is the one thing that turns "days" into
"weeks," so the architecture is shaped to contain it.

### 2.1 Separate the agent from the grader

The agent step and the grading step have different hardware needs, so they are different
processes with a file boundary between them:

```
instance ──► [AGENT, on the arm64 host]             ──► candidate.patch (git diff)
                checkout repo @ base_commit
                agent run "<issue_text>"            (Crush navigates/edits; reasoning=high)
                extract `git diff`
                                                    ── file boundary (patch is just text) ──►
             [GRADER, wherever Docker works best]  ──► {resolved: bool, fail_to_pass, pass_to_pass}
                apply candidate.patch
                run FAIL_TO_PASS + PASS_TO_PASS
                in the instance's environment
```

The agent never runs the test suite, so **no Docker/x86 test environment is needed on the arm64
agent host for the agent to work** — it only needs the source tree to read and edit. This is also
the fairness invariant: the scaffold that produces the patch is identical across arms; only the
model differs.

### 2.2 Grader placement — decided by M0, not asserted

Three candidate grader paths, in preference order. M0 (see §8) picks the one that actually works
for a pure-Python subset before we scale:

1. **arm64-native, on the agent host.** Build the instance environment from source on arm64 (many
   SWE-bench Verified instances are pure-Python: `django`, `sympy`, `flask`, `sphinx`, `requests`,
   `pylint`, `scikit-learn`-minus-native). Pick the subset from repos whose deps have arm64 wheels.
   Cheapest if it holds.
2. **x86 grader host.** Ship `candidate.patch` to a separate x86 box with Docker (`$GRADER_HOST`
   if reachable) and run the stock SWE-bench harness there. Full compatibility, adds a
   cross-machine dependency and a reachability assumption.
3. **qemu emulation on the agent host.** Last resort; correctness over speed for a small subset.

The spec does **not** pin the grader path — M0 does, honestly, and the writeup states which one ran.

---

## 3. The instrument: the subset and its validation gate

### 3.1 Subset construction

- Source: SWE-bench Verified (500 human-validated instances) via the HuggingFace dataset
  `princeton-nlp/SWE-bench_Verified` (fields: `instance_id`, `repo`, `base_commit`, `problem_statement`,
  `patch` (gold), `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `environment_setup_commit`).
- Curate **20–50** instances biased toward arm64-clean, pure-Python repos (per §2.2 path 1), across
  ≥3 distinct repos so a single repo's quirks don't dominate.
- Record the exact `instance_id` list in the repo (`subset.txt`) so runs are reproducible and the
  "which 30" is never ambiguous. Small-N and non-official-500 caveats travel with every number.

### 3.2 Validation gate — no model is scored until both hold

Before measuring any model, validate the **grader**:

1. **Gold-patch arm ≈ 100%.** Feed each instance's own `patch` as the candidate. If the grader is
   correct, every instance resolves. A miss means the environment/test wiring is wrong — fix the
   grader, not the model.
2. **Empty-patch arm ≈ 0%.** Feed an empty diff. `FAIL_TO_PASS` must still fail. A false "resolved"
   here means the grader isn't actually exercising the target tests — a silently-passing grader
   would make every model look good.

Measurement does not begin until the instrument is proven on both ends.

---

## 4. Experiment matrix

**Arms** — same subset, same scaffold, same seeds; only the model/config varies:

| Arm | Model / config | Question it answers |
|---|---|---|
| `infinity-high` | large open-weight MoE, reasoning_effort=high | our current driver-class ceiling |
| `infinity-low` | large open-weight MoE, reasoning_effort=low | **did reasoning=high actually help pass@1?** |
| `aurora` | driver-class open-weight coder model | is this the better driver (audit claim)? |
| `nova` | fast-tier open-weight coder model | fast-tier floor |
| `fable` | frontier API | the ceiling / escalation target — **Phase 1 stretch**, only if the API path (§10.3) is available; otherwise it's the first thing Phase 3 wires |
| `gold` / `empty` | §3.2 validation arms | instrument correctness |

**Fairness controls:** identical Crush scaffold, prompts, seeds, and instance order across arms;
any background autonomous agent loop and the model keepalive process are **paused** during timed
runs (they fight the harness for residency and inject latency noise). One arm per model resident
at a time (a single host's unified memory won't hold two driver-class models plus KV headroom).

**Metrics**

- *Quality:* pass@1 = fraction of subset **resolved** (all `FAIL_TO_PASS` pass **and** all
  `PASS_TO_PASS` still pass). Report mean + a bootstrap CI over instances.
- *Cost:* wall-clock per instance (p50/p95), tokens in/out (from Crush's request log, which we
  already parse), agent turns, timeouts.
- Report as a table + the accuracy-vs-cost frontier. **Never** report a subset number without the
  "N=… curated subset, not the official 500" caveat.

---

## 5. Failure handling

Failures are measured events, never silent drops:

| Failure | Behavior |
|---|---|
| Grader env fails to build for an instance | instance **excluded** from that run, listed in the report, counted |
| agent run times out (wall cap) | scored as **not resolved** (= empty patch), flagged |
| Candidate patch doesn't apply | **not resolved**, flagged (distinguished from "applied but tests fail") |
| Crush emits no diff (agent gave up) | **not resolved**, flagged |
| ollama/model crash mid-run | affected instances marked invalid, excluded, **counted** in the writeup |

Distinguishing "didn't apply" from "applied but failed tests" from "agent produced nothing" is
required — they point at different problems (harness bug vs model capability vs prompt).

---

## 6. Architecture / components

Small, testable units with file boundaries (so the routing/scoring logic is unit-testable with no
GPU and no Docker):

| Unit | Input → Output | Notes |
|---|---|---|
| `dataset.py` | subset.txt → list[Instance] | loads HF dataset, filters to subset |
| `agent_run.py` | Instance → candidate.patch | checkout @ base_commit, agent `run`, extract diff; per-arm model via `run --model <arm>` |
| `grader.py` | (Instance, patch) → Result{resolved, f2p, p2p, error} | applies patch, runs tests in the instance env; the ONE unit that needs Docker/env |
| `score.py` | list[Result] → report (pass@1, CI, cost table, frontier) | pure computation, GPU-free, unit-tested |
| `run.py` | arm, subset → orchestrates the above, writes `runs/<arm>-<ts>/` | resumable: skip instances already graded |

Traces per instance: `{instance_id, arm, patch, applied, f2p, p2p, resolved, wall_ms, tokens, error}`
as JSONL, so a run is auditable and re-scorable without re-running the agent.

---

## 7. Testing

| Level | Covers | GPU/Docker? |
|---|---|---|
| Unit | `score.py` math (pass@1, CI), patch-apply parsing, subset filtering | neither |
| Instrument | the §3.2 validation gate (gold≈100%, empty≈0%) | grader only |
| Smoke | one instance end-to-end through `agent_run` + `grader` | both |

The unit tier is GPU-free and Docker-free on purpose, so scoring/orchestration logic develops off
the agent host.

---

## 8. Milestones

| ID | Goal | Kill / decision criterion |
|---|---|---|
| **M0** | **Grader feasibility.** Get 3–5 pure-Python instances fully graded (gold-patch → resolved, empty-patch → unresolved) via §2.2 path 1 (arm64-native). | If arm64-native grading can't be made to work for pure-Python instances, switch to path 2 (x86 host) **before** building the subset. This is the milestone whose negative result reshapes the project — it runs first. |
| **M1** | `agent_run` produces a valid diff from the agent's `run` on one instance | — |
| **M2** | Subset curated (`subset.txt`, 20–50) + validation gate passes (gold≈100%, empty≈0%) | Blocks all model measurement |
| **M3** | All model arms scored on the subset; report + frontier | The result |
| **M4** | Writeup: our real pass@1 per arm, the reasoning-high verdict, cost frontier | Feeds Phase-2/3 go/no-go |

---

## 9. Scope guards

- **No fine-tuning.** All models frozen.
- **No new agent scaffold.** We measure Crush *as configured*; building a better scaffold is a
  different project (and would break the "measure our real harness" premise).
- **Phase 1 is measurement only.** Best-of-N and escalation are Phases 2–3, specced later.
- **Curated subset, not the full 500.** Numbers are internal, not leaderboard submissions; the
  caveat is mandatory on every reported figure.
- **Single arm64 host for the agent.** Grader may run elsewhere (M0 decides).

---

## 10. Open risks carried into implementation

1. **arm64 grading** (§2) — the load-bearing risk; M0 resolves it before the subset is built.
2. **x86 grader host reachability** — path 2 assumes a separate x86 Docker box (`$GRADER_HOST`) is
   up; if it isn't, path 1 or path 3 must carry. Not assumed reachable.
3. **Frontier API path from the agent host** — a *Phase 3* dependency, flagged now: escalation
   needs a frontier API reachable from the escalation logic (key + egress). Does not block Phase 1.
4. **Contamination** — SWE-bench Verified predates our models' training; absolute numbers may be
   optimistic vs held-out work. Relative arm comparison (our whole point) is unaffected.
5. **Small N** — 20–50 instances gives wide CIs. Enough to rank arms and answer the reasoning-high
   question; not enough for a decimal-precise leaderboard claim. Stated as such.
