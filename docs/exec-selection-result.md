# Execution-based selection — measured on bo13

Re-scored the existing `runs/nova-bestofn-bo13` run (nova, N=5, 13 instances) under
`select_by_execution` instead of diff-cluster majority vote. **No agent or grader was re-run**:
the regression signal was harvested from the per-instance `report.json` files swebench had
already written under `~/swe-grade-arm/logs/run_evaluation/nova-bo{0..4}-bo13/`, reading only
their `PASS_TO_PASS` section (`scripts/harvest_pass_to_pass.py`, saved as
`runs/nova-bestofn-bo13/pass_to_pass.json`).

| metric | value | |
|---|---|---|
| single-sample pass@1 | 41.5% | 27/65 (instance, sample) pairs |
| majority vote (previous deployable) | 46.2% | 6/13 |
| **execution-selected (deployable)** | **53.8%** | **7/13** |
| oracle pass@k ceiling | 61.5% | 8/13 |

**+7.7pp over vote — about half the 15.3pp that vote was leaving on the table.**

Regression verdicts were known for 55/65 candidates (46 clean, 9 regressed); the other 10 had no
usable report (errored or empty patch) and were passed to the selector as `None`, where it
degrades to the vote rather than discarding the candidate.

## The instance that matters

`psf__requests-1921` is the case that motivated the whole change: 3 of 5 candidates resolved, but
the 2 *failing* ones were textually identical while the 3 correct fixes were diverse diffs, so
diff-clustering picked the wrong cluster. Its harvested regression vector is
`[True, True, True, False, False]` — the two identical wrong candidates broke the repo's own
suite. Execution selection dropped them and picked index 0, which resolves.

`pylint-dev__pylint-4970` also changed selection (index 0 -> 1) but neither candidate resolves;
it is one of the instances no local sample solves.

## Caveats — do not oversell this

- **N=13, and the delta is a single instance** (6/13 -> 7/13). That is well inside noise for a
  bootstrap CI on 13 samples. It is directionally consistent with the mechanism and with the
  pre-registered case study, but it is not a significant result.
- The regression signal comes from the same grading pass that produced the oracle labels. The
  *selector* only ever reads `PASS_TO_PASS`, which is what makes it non-leaky — but a deployed
  agent would have to run the repo suite itself, which costs time this measurement did not pay.
- 10/65 candidates had no verdict, so the selector was running partly blind.

## Reproduce

```sh
ssh $GRADER_HOST 'python3 -' < scripts/harvest_pass_to_pass.py > runs/nova-bestofn-bo13/pass_to_pass.json
```
then feed that mapping to `exec_select.rescore_run(run_dir, regression)`.
