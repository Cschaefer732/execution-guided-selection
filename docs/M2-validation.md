# M2 — Instrument Validation

**Date:** 2026-07-25
**Grader host:** `$GRADER_HOST`, an x86 desktop (Docker 29.5, swebench 4.1.0). arm64 grading on the agent host is broken
(swebench pulls `sweb.eval.x86_64.*` images; the x86 container crashes instantly on aarch64).

## Validated subset (N=3)

The gold/empty gate passed on nova: the gold patch resolves every instance, the empty patch resolves
none.

```
spark-swe-eval m0 --host $GRADER_HOST ${(f)"$(grep -v '^#' subset.txt)"}
→ {'gold_pass_at_1': 1.0, 'empty_pass_at_1': 0.0, 'ok': True, 'host': '<grader host>'}
```

| instance | gold | empty |
|---|---|---|
| django__django-11099 | resolved ✅ | not resolved ✅ |
| pallets__flask-5014 | resolved ✅ | not resolved ✅ |
| pylint-dev__pylint-7080 | resolved ✅ | not resolved ✅ |

## Dropped by the gate (not silently omitted)

| instance | reason |
|---|---|
| psf__requests-2317 | gold patch does NOT resolve under swebench 4.1 (FAIL_TO_PASS not all passing) — untrustworthy |
| sphinx-doc__sphinx-8595 | gold patch does NOT resolve under swebench 4.1 — untrustworthy |

An instance whose *gold* patch can't resolve is untrustworthy for measuring models (a model
"failing" it tells us nothing), so the gate correctly excludes them. N=3 is a small first pass —
expandable by adding gold-passing instances and re-running the gate. Numbers carry wide CIs.

## Harness notes surfaced during validation

- **run_id must be unique per grade call** — swebench short-circuits (re-reports the cached run)
  when a run_id is reused across different instance sets. `m0()` now uses a uuid tag per call.
- **Report retrieval is a separate `ssh cat`** of the report file, not parsed from swebench's stdout.
- **Invocation footgun (zsh):** `$IDS` is NOT word-split by zsh; pass the subset via
  `${(f)"$(grep -v '^#' subset.txt)"}`, or let `run --subset` read the file itself.
