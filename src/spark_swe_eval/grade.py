"""Grade candidate patches via the swebench harness on a remote Docker host."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Result:
    instance_id: str
    arm: str
    resolved: bool
    error: bool
    unresolved: bool


def parse_report(report: dict, subset_ids: list[str], arm: str) -> list[Result]:
    resolved = set(report.get("resolved_ids", []))
    unresolved = set(report.get("unresolved_ids", []))
    empty = set(report.get("empty_patch_ids", []))  # agent produced no diff = a failure
    errored = set(report.get("error_ids", []))
    out: list[Result] = []
    for iid in subset_ids:
        is_resolved = iid in resolved
        is_unresolved = (iid in unresolved) or (iid in empty)
        # error = genuine harness failure (env didn't build / never ran), NOT a model failure
        is_error = (iid in errored) or not (is_resolved or is_unresolved)
        out.append(
            Result(
                instance_id=iid,
                arm=arm,
                resolved=is_resolved,
                error=is_error,
                unresolved=is_unresolved,
            )
        )
    return out


def build_grade_script(
    preds_remote: str,
    run_id: str,
    instance_ids: list[str],
    dataset: str,
    max_workers: int = 4,
    workdir: str = "~/swe-grade",
) -> str:
    ids = " ".join(shlex.quote(i) for i in instance_ids)
    preds = "gold" if preds_remote == "gold" else shlex.quote(preds_remote)
    return f"""cd {workdir} 2>/dev/null || mkdir -p {workdir} && cd {workdir}
python3 -m swebench.harness.run_evaluation \
  --dataset_name {dataset} --predictions_path {preds} --run_id {shlex.quote(run_id)} \
  --instance_ids {ids} --max_workers {int(max_workers)} --cache_level env || true
"""


def _report_name(arm: str, run_id: str) -> str:
    """swebench writes <model_name_or_path>.<run_id>.json; gold predictions use the name 'gold'."""
    model = "gold" if arm == "gold" else arm
    return f"{model}.{run_id}.json"


def run_grader(
    preds_path: Path,
    run_id: str,
    instance_ids: list[str],
    host: str,
    arm: str,
    dataset: str = "princeton-nlp/SWE-bench_Verified",
    gold: bool = False,
    max_workers: int = 4,
    workdir: str = "~/swe-grade",
) -> list[Result]:
    if gold:
        preds_remote = "gold"
    else:
        preds_remote = f"/tmp/{run_id}-preds.jsonl"
        subprocess.run(["scp", str(preds_path), f"{host}:{preds_remote}"], check=True)
    # Run swebench (its output is captured and discarded — a real pipe, not /dev/null,
    # which swebench needs to complete). The report lands in `workdir` as a file. On an
    # arm64 grader host use max_workers=1-2 — parallel emulated Docker builds are what
    # OOM'd our previous x86 grader host.
    script = build_grade_script(preds_remote, run_id, instance_ids, dataset, max_workers, workdir)
    subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", host, "bash -s"],
        input=script,
        capture_output=True,
        text=True,
        timeout=14400,
    )
    # Retrieve the report over a clean channel (parsing it out of swebench's flooded
    # stdout is unreliable — the report tail interleaves/truncates).
    fetch = f"cat {workdir}/{shlex.quote(_report_name(arm, run_id))} 2>/dev/null || echo '{{}}'"
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", host, fetch],
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = json.loads(proc.stdout.strip() or "{}")
    return parse_report(report, instance_ids, arm)
