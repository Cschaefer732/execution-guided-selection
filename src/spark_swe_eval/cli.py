"""spark-swe-eval CLI: m0 (feasibility), run (arms), score."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from spark_swe_eval.agent import (
    AGENT_CMD,
    AGENT_HOST,
    DEFAULT_AGENT_TIMEOUT,
    run_agent,
    sample_patches,
)
from spark_swe_eval.escalate import run_escalation
from spark_swe_eval.exec_select import rescore_run, run_regression_check, select_by_execution
from spark_swe_eval.grade import run_grader
from spark_swe_eval.instances import Instance, load_instances, read_subset
from spark_swe_eval.phase2 import RegressionFn, SelectFn, per_candidate_grades, run_bestofn
from spark_swe_eval.predictions import prediction_line, write_predictions
from spark_swe_eval.regrade import regrade_export
from spark_swe_eval.remote import run as ssh_run
from spark_swe_eval.score import arm_summary, pass_at_1

GRADER_HOST = os.environ.get("GRADER_HOST", "localhost")


def m0_verdict(gold_p1: float, empty_p1: float) -> dict:
    return {
        "gold_pass_at_1": gold_p1,
        "empty_pass_at_1": empty_p1,
        "ok": gold_p1 >= 0.9 and empty_p1 <= 0.1,
    }


def m0(host: str, instance_ids: list[str]) -> dict:
    tag = uuid.uuid4().hex[:8]  # unique run_id per call: swebench short-circuits on a reused id
    gold = run_grader(Path("/dev/null"), f"m0gold-{tag}", instance_ids, host, "gold", gold=True)
    empty_preds = [prediction_line(i, "empty", "") for i in instance_ids]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        write_predictions(empty_preds, Path(f.name))
        empty_path = Path(f.name)
    empty = run_grader(empty_path, f"m0empty-{tag}", instance_ids, host, "empty")
    v = m0_verdict(pass_at_1(gold), pass_at_1(empty))
    v["host"] = host
    return v


def run_dir(base: Path, arm: str, ts: str) -> Path:
    d = base / "runs" / f"{arm}-{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def already_done(run_dir: Path) -> set[str]:
    tp = run_dir / "traces.jsonl"
    if not tp.exists():
        return set()
    return {json.loads(line)["instance_id"] for line in tp.read_text().splitlines() if line.strip()}


def _set_reasoning(level: str, host: str) -> None:
    if level:
        ssh_run(host, f"{AGENT_CMD} reasoning {level}", timeout=30)


def run_arm(
    arm: str,
    subset_path: Path,
    host_agent: str,
    host_grader: str,
    ts: str,
    reasoning: str = "",
    max_workers: int = 4,
    workdir: str = "~/swe-grade",
    base: Path | None = None,
    harness: str = "frozen",
) -> dict:
    base = base or Path.cwd()
    ids = read_subset(subset_path)
    instances = load_instances(ids)
    d = run_dir(base, arm, ts)
    done = already_done(d)
    _set_reasoning(reasoning, host_agent)

    patches: dict[str, str] = {}
    with (d / "traces.jsonl").open("a") as tf:
        for inst in instances:
            if inst.instance_id in done:
                continue
            patch = run_agent(inst, arm, host=host_agent, harness=harness)
            patches[inst.instance_id] = patch
            tf.write(
                json.dumps({"instance_id": inst.instance_id, "arm": arm, "has_patch": bool(patch)})
                + "\n"
            )

    preds = [prediction_line(i, arm, p) for i, p in patches.items()]
    preds_path = d / "predictions.jsonl"
    write_predictions(preds, preds_path)
    results = run_grader(
        preds_path,
        f"{arm}-{ts}",
        list(patches),
        host_grader,
        arm,
        max_workers=max_workers,
        workdir=workdir,
    )
    (d / "results.jsonl").write_text("".join(json.dumps(r.__dict__) + "\n" for r in results))
    summary = arm_summary(results)
    (d / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def make_grade_fn(
    arm: str, host_grader: str, ts: str, max_workers: int = 1, workdir: str = "~/swe-grade"
):
    """Grade one best-of-N sample slot: {instance_id: patch} -> {instance_id: resolved}."""

    def grade_fn(k: int, preds_map: dict[str, str]) -> dict[str, bool]:
        print(
            f"[grade] slot {k}: {len(preds_map)} preds on {host_grader}",
            file=sys.stderr,
            flush=True,
        )
        run_id = f"{arm}-bo{k}-{ts}"
        rows = [prediction_line(iid, arm, patch) for iid, patch in preds_map.items()]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            write_predictions(rows, Path(f.name))
            preds_path = Path(f.name)
        results = run_grader(
            preds_path,
            run_id,
            list(preds_map),
            host_grader,
            arm,
            max_workers=max_workers,
            workdir=workdir,
        )
        return {r.instance_id: r.resolved for r in results}

    return grade_fn


def make_regression_fn(
    by_id: dict[str, Instance], host_grader: str, workdir: str = "~/swe-grade-regress"
) -> RegressionFn:
    """Regression-check one best-of-N sample slot: {instance_id: patch} -> {instance_id:
    regression_ok}. Only ever runs PASS_TO_PASS — never touches FAIL_TO_PASS."""

    def regression_fn(k: int, preds_map: dict[str, str]) -> dict[str, bool | None]:
        out: dict[str, bool | None] = {}
        for iid, patch in preds_map.items():
            wd = f"{workdir}/{iid}/s{k}"
            out[iid] = run_regression_check(host_grader, wd, by_id[iid], patch)
        return out

    return regression_fn


def run_bestofn_arm(
    arm: str,
    subset_path: Path,
    host_agent: str,
    host_grader: str,
    n: int,
    ts: str,
    reasoning: str = "",
    scaffold: str = "bare",
    max_workers: int = 1,
    workdir: str = "~/swe-grade",
    selector: str = "vote",
    base: Path | None = None,
) -> dict:
    base = base or Path.cwd()
    ids = read_subset(subset_path)
    by_id = {i.instance_id: i for i in load_instances(ids)}
    d = run_dir(base, f"{arm}-bestofn", ts)
    _set_reasoning(reasoning, host_agent)

    captured: dict[str, list[str]] = {}

    def sample_fn(iid: str) -> list[str]:
        ps = sample_patches(by_id[iid], arm, n, host=host_agent, scaffold=scaffold)
        captured[iid] = ps
        return ps

    grade_fn = make_grade_fn(arm, host_grader, ts, max_workers, workdir)
    regression_fn: RegressionFn | None = None
    select_fn: SelectFn | None = None
    if selector == "exec":
        regression_fn = make_regression_fn(by_id, host_grader)
        select_fn = select_by_execution
    out = run_bestofn(ids, arm, n, sample_fn, grade_fn, regression_fn, select_fn)
    (d / "patches.json").write_text(json.dumps(captured, indent=2))  # persist for re-analysis
    (d / "bestofn.json").write_text(json.dumps(out, indent=2))
    grades = per_candidate_grades(out["per_instance"])  # free DPO grades from this same run
    (d / "candidate_grades.json").write_text(json.dumps(grades, indent=2))
    return out


def rescore_cmd(run_dir_path: Path, regression_path: Path | None) -> dict:
    """Re-score an existing saved best-of-N run dir under select_by_execution, without
    re-running any agent or grader. `regression_path` (optional) is a JSON file mapping
    instance_id -> per-candidate list of true/false/null, aligned with patches.json's order."""
    regression = json.loads(regression_path.read_text()) if regression_path else None
    out = rescore_run(run_dir_path, regression)
    (run_dir_path / "rescored.json").write_text(json.dumps(out, indent=2))
    return out


def regrade_export_cmd(run_dir_path: Path) -> dict:
    """Backfill `candidate_grades.json` for an existing best-of-N run dir (predates the field,
    or a run that failed before it was written). Writes exactly the map — same shape as the
    field `run_bestofn_arm` now persists live — so a consumer doesn't need to know which path
    produced it. Instances with no recoverable evidence are named in the return value, never
    silently dropped from it."""
    grades, unrecoverable = regrade_export(run_dir_path)
    (run_dir_path / "candidate_grades.json").write_text(json.dumps(grades, indent=2))
    return {"candidate_grades": grades, "unrecoverable_instances": unrecoverable}


def make_escalation_sample_fn(
    by_id: dict[str, Instance], host_agent: str, timeouts: dict[str, int] | None = None
):
    """(instance_id, arm) -> patch. Reused for both the local pass and the frontier re-run —
    `arm` selects which model the agent's `run --model` invokes. `timeouts` gives the escalation
    target its own wall clock: a slower model on the same budget is measured on its timeout
    rather than its reasoning."""

    def sample_fn(iid: str, arm: str) -> str:
        timeout_s = (timeouts or {}).get(arm, DEFAULT_AGENT_TIMEOUT)
        return run_agent(by_id[iid], arm, host=host_agent, timeout_s=timeout_s)

    return sample_fn


def make_escalation_regression_fn(
    by_id: dict[str, Instance], host_grader: str, workdir: str = "~/swe-grade-regress-esc"
):
    """(instance_id, patch) -> regression_ok. Only ever runs PASS_TO_PASS — never touches
    FAIL_TO_PASS."""

    def regression_fn(iid: str, patch: str) -> bool | None:
        return run_regression_check(host_grader, f"{workdir}/{iid}", by_id[iid], patch)

    return regression_fn


def make_escalation_grade_fn(
    arm_label: str, host_grader: str, ts: str, max_workers: int = 1, workdir: str = "~/swe-grade"
):
    """(label, {iid: patch}) -> {iid: resolved}. `label` ("local"/"final") disambiguates the
    swebench run_id between the local-baseline grading pass and the final mixed-set pass."""

    def grade_fn(label: str, preds_map: dict[str, str]) -> dict[str, bool]:
        run_id = f"{arm_label}-esc-{label}-{ts}"
        rows = [prediction_line(iid, arm_label, patch) for iid, patch in preds_map.items()]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            write_predictions(rows, Path(f.name))
            preds_path = Path(f.name)
        results = run_grader(
            preds_path,
            run_id,
            list(preds_map),
            host_grader,
            arm_label,
            max_workers=max_workers,
            workdir=workdir,
        )
        return {r.instance_id: r.resolved for r in results}

    return grade_fn


def run_escalation_arm(
    local_arm: str,
    frontier_arm: str,
    subset_path: Path,
    host_agent: str,
    host_grader: str,
    ts: str,
    max_workers: int = 1,
    workdir: str = "~/swe-grade",
    escalate_on_unknown: bool = True,
    base: Path | None = None,
    local_timeout: int = DEFAULT_AGENT_TIMEOUT,
    frontier_timeout: int = DEFAULT_AGENT_TIMEOUT,
) -> dict:
    base = base or Path.cwd()
    ids = read_subset(subset_path)
    by_id = {i.instance_id: i for i in load_instances(ids)}
    instances = [by_id[i] for i in ids]
    label = f"{local_arm}-escalate"
    d = run_dir(base, label, ts)

    out = run_escalation(
        instances,
        local_arm,
        frontier_arm,
        make_escalation_sample_fn(
            by_id, host_agent, {local_arm: local_timeout, frontier_arm: frontier_timeout}
        ),
        make_escalation_regression_fn(by_id, host_grader),
        make_escalation_grade_fn(label, host_grader, ts, max_workers, workdir),
        escalate_on_unknown,
    )
    (d / "escalation.json").write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="spark-swe-eval")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_m0 = sub.add_parser("m0")
    p_m0.add_argument("--host", default=GRADER_HOST)
    p_m0.add_argument("instance_ids", nargs="+")

    p_run = sub.add_parser("run")
    p_run.add_argument("--arm", required=True)
    p_run.add_argument("--subset", default="subset.txt")
    p_run.add_argument("--host-agent", default=AGENT_HOST)
    p_run.add_argument("--host-grader", default=GRADER_HOST)
    p_run.add_argument("--reasoning", default="")
    p_run.add_argument("--max-workers", type=int, default=4)
    p_run.add_argument("--workdir", default="~/swe-grade")
    p_run.add_argument("--ts", default=os.environ.get("SWE_TS", "manual"))
    # frozen (default) pins the 2026-07-28 eval config snapshot, so numbers stay comparable
    # across months. live runs whatever harness is actually deployed — the only way a run can
    # detect a harness change, and not comparable to earlier frozen numbers.
    p_run.add_argument("--harness", default="frozen", choices=["frozen", "live"])

    p_bo = sub.add_parser("bestofn")
    p_bo.add_argument("--arm", required=True)
    p_bo.add_argument("--subset", default="subset.txt")
    p_bo.add_argument("--n", type=int, default=5)
    p_bo.add_argument("--host-agent", default=AGENT_HOST)
    p_bo.add_argument("--host-grader", default=GRADER_HOST)
    p_bo.add_argument("--reasoning", default="")
    p_bo.add_argument("--scaffold", default="bare", choices=["bare", "guided"])
    p_bo.add_argument("--max-workers", type=int, default=1)
    p_bo.add_argument("--workdir", default="~/swe-grade")
    p_bo.add_argument("--selector", default="vote", choices=["vote", "exec"])
    p_bo.add_argument("--ts", default=os.environ.get("SWE_TS", "manual"))

    p_rs = sub.add_parser("rescore")
    p_rs.add_argument("--run-dir", required=True)
    p_rs.add_argument("--regression-json", default=None)

    p_re = sub.add_parser("regrade-export")
    p_re.add_argument("--run-dir", required=True)

    p_esc = sub.add_parser("escalate")
    p_esc.add_argument("--local-arm", required=True)
    p_esc.add_argument("--frontier-arm", default="opus5")
    p_esc.add_argument("--subset", default="subset.txt")
    p_esc.add_argument("--host-agent", default=AGENT_HOST)
    p_esc.add_argument("--host-grader", default=GRADER_HOST)
    p_esc.add_argument("--max-workers", type=int, default=1)
    p_esc.add_argument("--workdir", default="~/swe-grade")
    p_esc.add_argument("--ts", default=os.environ.get("SWE_TS", "manual"))
    p_esc.add_argument("--escalate-on-unknown", action=argparse.BooleanOptionalAction, default=True)
    p_esc.add_argument("--local-timeout", type=int, default=DEFAULT_AGENT_TIMEOUT)
    # the escalation target is a bigger, slower model; same budget would measure its timeout
    p_esc.add_argument("--frontier-timeout", type=int, default=2 * DEFAULT_AGENT_TIMEOUT)

    args = ap.parse_args()
    if args.cmd == "m0":
        print(m0(args.host, args.instance_ids))
    elif args.cmd == "run":
        print(
            run_arm(
                args.arm,
                Path(args.subset),
                args.host_agent,
                args.host_grader,
                args.ts,
                args.reasoning,
                args.max_workers,
                args.workdir,
                harness=args.harness,
            )
        )
    elif args.cmd == "bestofn":
        print(
            run_bestofn_arm(
                args.arm,
                Path(args.subset),
                args.host_agent,
                args.host_grader,
                args.n,
                args.ts,
                args.reasoning,
                args.scaffold,
                args.max_workers,
                args.workdir,
                args.selector,
            )
        )
    elif args.cmd == "rescore":
        regression_path = Path(args.regression_json) if args.regression_json else None
        print(rescore_cmd(Path(args.run_dir), regression_path))
    elif args.cmd == "regrade-export":
        print(regrade_export_cmd(Path(args.run_dir)))
    elif args.cmd == "escalate":
        print(
            run_escalation_arm(
                args.local_arm,
                args.frontier_arm,
                Path(args.subset),
                args.host_agent,
                args.host_grader,
                args.ts,
                args.max_workers,
                args.workdir,
                args.escalate_on_unknown,
            )
        )


if __name__ == "__main__":
    main()
