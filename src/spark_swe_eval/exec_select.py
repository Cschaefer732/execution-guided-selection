"""Execution-based candidate selection: prefer candidates that pass PASS_TO_PASS.

Pure selection logic (`select_by_execution`, `rescore_run`) never touches Docker/SSH and can be
unit-tested or re-run offline from a saved `patches.json` + `bestofn.json`. Execution I/O
(`run_regression_check`) is isolated in its own function.

NEVER read the grader's held-out resolution oracle here. Only PASS_TO_PASS (the repo's own
regression suite) may inform selection; that's what any deployed agent could run itself.
"""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
from collections import Counter
from pathlib import Path

from spark_swe_eval.bestofn import _usable, cluster_key
from spark_swe_eval.instances import Instance
from spark_swe_eval.remote import run


def select_by_execution(patches: list[str], regression_ok: list[bool | None]) -> int:
    """Index of the chosen candidate, or -1 if none is usable. Never inspects test results
    beyond `regression_ok` (PASS_TO_PASS outcomes supplied by the caller).

    Prefers candidates whose regression check passed; degrades to the full usable set if none
    did (a degraded pick beats no pick). Ties within the preferred set go to the diff-cluster
    majority vote, then shortest patch, then lowest index."""
    usable = [i for i, p in enumerate(patches) if _usable(p)]
    if not usable:
        return -1
    passing = [i for i in usable if regression_ok[i] is True]
    pool = passing if passing else usable
    counts = Counter(cluster_key(patches[i]) for i in pool)
    best_size = max(counts.values())
    winners = [i for i in pool if counts[cluster_key(patches[i])] == best_size]
    winners.sort(key=lambda i: (len(patches[i]), i))
    return winners[0]


def build_regression_script(instance: Instance, patch: str, workdir: str) -> str:
    if not workdir.strip() or workdir.strip() in {"/", "~", "$HOME"}:
        raise ValueError(f"refusing to use workdir {workdir!r}")
    tests = " ".join(shlex.quote(t) for t in instance.pass_to_pass)
    wd = shlex.quote(workdir)
    patch_b64 = base64.b64encode(patch.encode()).decode()
    # Distinct exit codes for clone/checkout/apply failures (90/91) so they can never be mistaken
    # for pytest's own exit code 1 ("tests failed") by the caller. The RESULT marker is what
    # proves pytest actually collected and ran tests; without it, exit 1 is ambiguous between
    # "a test failed" and "imports/collection blew up", and the latter is an infra error.
    return f"""find {wd} -mindepth 1 -delete 2>/dev/null || true
mkdir -p {wd} || exit 90
git clone --quiet https://github.com/{instance.repo}.git {wd} || exit 90
cd {wd} || exit 90
git checkout --quiet {shlex.quote(instance.base_commit)} || exit 90
echo {patch_b64} | base64 -d | git apply - || exit 91
python3 -m pytest -q -p no:cacheprovider {tests}
echo "RESULT_EXIT=$?"
"""


def run_regression_check(host: str, workdir: str, instance: Instance, patch: str) -> bool | None:
    """Apply `patch` at `instance.base_commit` and run ONLY `instance.pass_to_pass`.

    True: all pass_to_pass tests pass. False: at least one genuinely failed. None: infra error
    (clone/checkout/apply failed, ssh dropped, deps missing, nothing collected) — MUST NOT be
    reported as False, or an infra hiccup masquerades as a capability failure.

    A bare clone has no dependencies installed, and SWE-bench PASS_TO_PASS ids are not always
    pytest ids (Django uses `test_x (module.Class)`), so a plain exit code is ambiguous. Only a
    run that reached the RESULT_EXIT marker with collected tests is trusted; everything else is
    None. To get a verdict on those instances, run this inside the instance's SWE-bench image
    instead of a bare clone."""
    if not instance.pass_to_pass:
        return True
    script = build_regression_script(instance, patch, workdir)
    try:
        code, out, _ = run(host, script, timeout=1200)
    except subprocess.TimeoutExpired:
        return None
    if "RESULT_EXIT=" not in out:
        return None
    marker = out.rsplit("RESULT_EXIT=", 1)[1].strip().split()[0]
    if marker == "0":
        return True
    # exit 1 is "tests failed" only when pytest actually collected and ran something;
    # collection/usage/internal errors (2-5) and import failures are infra, not regressions.
    if marker == "1" and ("passed" in out or "failed" in out) and "error" not in out.lower():
        return False
    return None


def regression_from_instance_report(report: dict) -> bool | None:
    """PASS_TO_PASS verdict from a swebench per-instance report.json.

    swebench already runs the repo's own suite inside the instance's prepared image, so this
    gets a correct verdict on dependency-heavy and non-pytest repos that a bare clone cannot
    (Django's runner, missing deps). Only the PASS_TO_PASS section is read; the held-out
    section is the grader's answer key and must never reach the selector — the leak-guard test
    enforces that this module does not so much as name it.

    True: every PASS_TO_PASS test succeeded. False: at least one failed. None: the section is
    absent or empty (the instance errored, or the image never ran) — never False."""
    if not report:
        return None
    inner = report
    # per-instance reports are usually keyed by instance id
    if len(report) == 1:
        (only,) = report.values()
        if isinstance(only, dict) and "tests_status" in only:
            inner = only
    status = inner.get("tests_status")
    if not isinstance(status, dict):
        return None
    p2p = status.get("PASS_TO_PASS")
    if not isinstance(p2p, dict):
        return None
    success = p2p.get("success") or []
    failure = p2p.get("failure") or []
    if not success and not failure:
        return None
    return not failure


def build_instance_report_script(run_id: str, arm: str, instance_id: str, workdir: str) -> str:
    """Cat the per-instance report swebench writes under its run_evaluation log tree."""
    path = (
        f"{workdir}/logs/run_evaluation/{shlex.quote(run_id)}/{shlex.quote(arm)}/"
        f"{shlex.quote(instance_id)}/report.json"
    )
    return f"cat {path} 2>/dev/null || echo '{{}}'\n"


def rescore_run(run_dir: Path, regression: dict[str, list[bool | None]] | None = None) -> dict:
    """Re-score a saved best-of-N run (`patches.json` + `bestofn.json`) under
    `select_by_execution`, without re-running any agent or grader.

    `regression` maps instance_id -> per-candidate regression_ok (True/False/None), aligned with
    `patches.json`'s candidate order. Missing/omitted instances default to all-None, which makes
    `select_by_execution` degrade to the same vote it would have made with no regression info at
    all — i.e. this reproduces the current (vote-only) numbers as a sanity check."""
    patches: dict[str, list[str]] = json.loads((run_dir / "patches.json").read_text())
    bestofn: dict = json.loads((run_dir / "bestofn.json").read_text())
    regression = regression or {}

    per_instance: dict[str, dict] = {}
    for iid, ps in patches.items():
        resolved_per_candidate: list[bool] = bestofn["per_instance"][iid]["resolved_per_candidate"]
        reg_ok = regression.get(iid, [None] * len(ps))
        idx = select_by_execution(ps, reg_ok)
        per_instance[iid] = {
            "oracle_resolved": any(resolved_per_candidate),
            "deployable_resolved": idx >= 0 and resolved_per_candidate[idx],
            "selected_index": idx,
            "n_candidates": len(ps),
            "resolved_per_candidate": resolved_per_candidate,
        }

    instances = len(per_instance)
    oracle_resolved = sum(v["oracle_resolved"] for v in per_instance.values())
    deployable_resolved = sum(v["deployable_resolved"] for v in per_instance.values())
    total_candidates = sum(v["n_candidates"] for v in per_instance.values())
    single_resolved = sum(sum(v["resolved_per_candidate"]) for v in per_instance.values())
    return {
        "arm": bestofn.get("arm", "?"),
        "N": bestofn.get("N"),
        "instances": instances,
        "oracle_resolved": oracle_resolved,
        "deployable_resolved": deployable_resolved,
        "oracle_pass_at_k": oracle_resolved / instances if instances else 0.0,
        "deployable_pass_at_1": deployable_resolved / instances if instances else 0.0,
        "single_sample_pass_at_1": single_resolved / total_candidates if total_candidates else 0.0,
        "per_instance": per_instance,
    }
