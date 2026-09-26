"""Best-of-N orchestration: sample N patches per instance, grade every candidate, then report
BOTH the oracle pass@k ceiling and the deployable best-of-N number (see bestofn.py).

I/O is injected (`sample_fn`, `grade_fn`) so the control flow is unit-testable without the Spark
or the grader. Each of the N sample slots is graded as its own single-patch-per-instance pass
(swebench keys predictions by instance_id, so the N candidates for one instance cannot share a
predictions file — they must be graded in separate slots)."""

from __future__ import annotations

from collections.abc import Callable

from spark_swe_eval.bestofn import Candidate, aggregate_instance

SampleFn = Callable[[str], list[str]]  # instance_id -> N candidate patches
GradeFn = Callable[
    [int, dict[str, str]], dict[str, bool]
]  # (slot_k, {iid: patch}) -> {iid: resolved}
RegressionFn = Callable[
    [int, dict[str, str]], dict[str, bool | None]
]  # (slot_k, {iid: patch}) -> {iid: regression_ok}
SelectFn = Callable[[list[str], list[bool | None]], int]  # (patches, regression_ok) -> index


def run_bestofn(
    instance_ids: list[str],
    arm: str,
    n: int,
    sample_fn: SampleFn,
    grade_fn: GradeFn,
    regression_fn: RegressionFn | None = None,
    select_fn: SelectFn | None = None,
) -> dict:
    patches: dict[str, list[str]] = {iid: sample_fn(iid) for iid in instance_ids}
    resolved: dict[str, list[bool]] = {iid: [False] * n for iid in instance_ids}
    regression: dict[str, list[bool | None]] = {iid: [None] * n for iid in instance_ids}

    for k in range(n):
        preds = {iid: patches[iid][k] for iid in instance_ids}
        graded = grade_fn(k, preds)
        for iid, is_resolved in graded.items():
            resolved[iid][k] = is_resolved
        if regression_fn is not None:
            for iid, ok in regression_fn(k, preds).items():
                regression[iid][k] = ok

    per_instance: dict[str, dict] = {}
    for iid in instance_ids:
        cands = [Candidate(patches[iid][k], resolved[iid][k]) for k in range(n)]
        idx = select_fn(patches[iid], regression[iid]) if select_fn is not None else None
        agg = aggregate_instance(cands, selected_index=idx)
        agg["resolved_per_candidate"] = list(resolved[iid])
        agg["nonempty_per_candidate"] = [bool(patches[iid][k].strip()) for k in range(n)]
        per_instance[iid] = agg

    oracle = sum(a["oracle_resolved"] for a in per_instance.values())
    deployable = sum(a["deployable_resolved"] for a in per_instance.values())
    # expected single-sample pass@1 = mean resolution over every (instance, sample) — the baseline
    # best-of-N is measured against.
    total_candidates = len(instance_ids) * n
    single_resolved = sum(sum(resolved[iid]) for iid in instance_ids)
    graded_n = len(instance_ids)
    return {
        "arm": arm,
        "N": n,
        "instances": graded_n,
        "oracle_resolved": oracle,
        "deployable_resolved": deployable,
        "oracle_pass_at_k": oracle / graded_n if graded_n else 0.0,
        "deployable_pass_at_1": deployable / graded_n if graded_n else 0.0,
        "single_sample_pass_at_1": single_resolved / total_candidates if total_candidates else 0.0,
        "per_instance": per_instance,
    }


def per_candidate_grades(per_instance: dict[str, dict]) -> dict[str, bool]:
    """Flatten `run_bestofn`'s `per_instance[iid]["resolved_per_candidate"]` lists into the
    "<instance_id>#<candidate_idx>" -> resolved map DPO preference-pair extraction wants
    (`candidate_idx` is the index into that instance's `patches.json` list). This is the exact
    verdict each candidate was graded to compute oracle pass@k — captured at its source instead
    of being discarded once the aggregate counts are derived."""
    return {
        f"{iid}#{k}": bool(resolved)
        for iid, agg in per_instance.items()
        for k, resolved in enumerate(agg["resolved_per_candidate"])
    }
