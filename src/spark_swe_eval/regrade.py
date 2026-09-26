"""Backfill `candidate_grades.json` for a best-of-N run dir that predates it.

Pure, read-only over a saved run dir (no ssh, no docker) — mirrors exec_select.rescore_run's
"re-derive from what's on disk" pattern. Never guesses: an instance's candidates are recovered
only when EVERY one of them has a determinate verdict from a single evidence source; otherwise
the whole instance is reported unrecoverable and contributes nothing to the map.

Evidence, preferred in order:
1. `bestofn.json`'s `per_instance[iid]["resolved_per_candidate"]` — the per-candidate verdicts
   `run_bestofn` already computed and wrote out for this run (current schema, see phase2.py).
2. swebench's own `logs/run_evaluation/<run_id>/<arm>/<iid>/report.json`, one per sample slot,
   for the (rarer) case those raw grader logs were kept under the run dir. `run_id` follows
   `make_grade_fn`'s scheme, `"{arm}-bo{k}-{ts}"`, with `ts` recovered from the run dir's own
   name (`"{arm}-bestofn-{ts}"`, from `run_dir()` in cli.py).
"""

from __future__ import annotations

import json
from pathlib import Path


def _run_id_ts(run_dir: Path, arm: str) -> str | None:
    marker = f"{arm}-bestofn-"
    name = run_dir.name
    if not name.startswith(marker):
        return None
    return name[len(marker) :]


def _report_verdict(report: dict) -> bool | None:
    """The grading verdict from a swebench per-instance report.json. Unlike
    exec_select.regression_from_instance_report (which must never see FAIL_TO_PASS — it feeds
    a non-leaky selector), this consumer IS meant to see the oracle: DPO training pairs are
    built FROM the graded outcome, not used to pick a candidate blind to it."""
    if not report:
        return None
    inner = report
    if len(report) == 1:
        (only,) = report.values()
        if isinstance(only, dict):
            inner = only
    if "resolved" in inner:
        return bool(inner["resolved"])
    status = inner.get("tests_status")
    if not isinstance(status, dict):
        return None
    f2p = status.get("FAIL_TO_PASS")
    if not isinstance(f2p, dict):
        return None
    f2p_success = f2p.get("success") or []
    f2p_failure = f2p.get("failure") or []
    if not f2p_success and not f2p_failure:
        return None
    p2p_failure = (status.get("PASS_TO_PASS") or {}).get("failure") or []
    return not f2p_failure and not p2p_failure


def _report_path(run_dir: Path, run_id: str, arm: str, instance_id: str) -> Path:
    return run_dir / "logs" / "run_evaluation" / run_id / arm / instance_id / "report.json"


def _from_logs(run_dir: Path, arm: str, ts: str, iid: str, n: int) -> list[bool] | None:
    verdicts: list[bool | None] = []
    for k in range(n):
        run_id = f"{arm}-bo{k}-{ts}"
        path = _report_path(run_dir, run_id, arm, iid)
        report = json.loads(path.read_text()) if path.exists() else {}
        verdicts.append(_report_verdict(report))
    if any(v is None for v in verdicts):
        return None
    return [bool(v) for v in verdicts]


def regrade_export(run_dir: Path) -> tuple[dict[str, bool], list[str]]:
    """Reconstruct the "<instance_id>#<candidate_idx>" -> resolved map for an existing run dir.

    Returns (candidate_grades, unrecoverable_instance_ids). Instances with no complete evidence
    trail are named, not silently dropped or guessed at."""
    bestofn_path = run_dir / "bestofn.json"
    patches_path = run_dir / "patches.json"
    bestofn: dict = json.loads(bestofn_path.read_text()) if bestofn_path.exists() else {}
    patches: dict[str, list[str]] = (
        json.loads(patches_path.read_text()) if patches_path.exists() else {}
    )
    per_instance: dict[str, dict] = bestofn.get("per_instance", {})
    arm = bestofn.get("arm", "")
    ts = _run_id_ts(run_dir, arm) if arm else None

    instance_ids = list(patches) if patches else list(per_instance)

    grades: dict[str, bool] = {}
    unrecoverable: list[str] = []

    for iid in instance_ids:
        agg = per_instance.get(iid, {})
        n = len(patches[iid]) if iid in patches else agg.get("n_candidates")
        if not n:
            unrecoverable.append(iid)
            continue

        resolved_per_candidate = agg.get("resolved_per_candidate")
        if isinstance(resolved_per_candidate, list) and len(resolved_per_candidate) == n:
            for k, resolved in enumerate(resolved_per_candidate):
                grades[f"{iid}#{k}"] = bool(resolved)
            continue

        recovered = _from_logs(run_dir, arm, ts, iid, n) if ts is not None else None
        if recovered is not None:
            for k, resolved in enumerate(recovered):
                grades[f"{iid}#{k}"] = resolved
            continue

        unrecoverable.append(iid)

    return grades, unrecoverable
