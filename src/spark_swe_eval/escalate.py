"""Phase 3: escalate-to-frontier. Run the local arm first, detect which instances it probably
failed using ONLY non-leaky signals, and re-run just those on a frontier arm.

NEVER read the instance's held-out resolution test or any grader result to decide whether to
escalate — that's the answer key. A deployed agent could not see it, so using it here would make
the whole measurement meaningless. The only allowed signals are things a deployed agent could
compute itself: whether its own patch is empty/unusable, and the PASS_TO_PASS regression check
(which the agent could also run locally).

I/O is injected (`sample_fn`, `regression_fn`, `grade_fn`), same style as `phase2.run_bestofn`, so
the control flow is unit-testable without SSH/Docker."""

from __future__ import annotations

from collections.abc import Callable

from spark_swe_eval.bestofn import _usable
from spark_swe_eval.instances import Instance

SampleFn = Callable[[str, str], str]  # (instance_id, arm) -> patch
RegressionFn = Callable[[str, str], bool | None]  # (instance_id, patch) -> regression_ok
GradeFn = Callable[
    [str, dict[str, str]], dict[str, bool]
]  # (label, {iid: patch}) -> {iid: resolved}


def should_escalate(
    patch: str, regression_ok: bool | None, escalate_on_unknown: bool = True
) -> bool:
    """True if `patch` should be re-attempted on the frontier arm.

    Escalate when the local patch is empty/unusable, or when it broke its own PASS_TO_PASS
    regression suite. An unknown (None) regression result is a policy call — infra flakiness
    shouldn't silently suppress escalation, so it defaults to escalating, but callers that would
    rather save frontier spend on ambiguous cases can flip `escalate_on_unknown` off."""
    if not _usable(patch):
        return True
    if regression_ok is False:
        return True
    if regression_ok is None:
        return escalate_on_unknown
    return False


def run_escalation(
    instances: list[Instance],
    local_arm: str,
    frontier_arm: str,
    sample_fn: SampleFn,
    regression_fn: RegressionFn,
    grade_fn: GradeFn,
    escalate_on_unknown: bool = True,
) -> dict:
    local_patches: dict[str, str] = {}
    regression: dict[str, bool | None] = {}
    escalated_flags: dict[str, bool] = {}
    for inst in instances:
        iid = inst.instance_id
        patch = sample_fn(iid, local_arm)
        local_patches[iid] = patch
        reg_ok = regression_fn(iid, patch)
        regression[iid] = reg_ok
        escalated_flags[iid] = should_escalate(patch, reg_ok, escalate_on_unknown)

    escalated_ids = [inst.instance_id for inst in instances if escalated_flags[inst.instance_id]]
    frontier_patches = {iid: sample_fn(iid, frontier_arm) for iid in escalated_ids}

    frontier_empty = 0
    final_patches: dict[str, str] = {}
    per_instance: dict[str, dict] = {}
    for inst in instances:
        iid = inst.instance_id
        escalated = escalated_flags[iid]
        local_usable = _usable(local_patches[iid])
        frontier_usable = _usable(frontier_patches.get(iid, "")) if escalated else False
        if escalated and not frontier_usable:
            frontier_empty += 1  # billing/infra tripwire: escalated but frontier gave nothing back
        # never regress to an empty patch just because escalation ran - fall back to local
        final_patches[iid] = (
            frontier_patches[iid] if (escalated and frontier_usable) else local_patches[iid]
        )
        per_instance[iid] = {
            "escalated": escalated,
            "regression_ok": regression[iid],
            "local_usable": local_usable,
            "frontier_usable": frontier_usable,
        }

    final_resolved = grade_fn("final", final_patches)
    # local baseline only needs a fresh grading pass for escalated instances - non-escalated
    # instances' local patch IS the final patch, already graded above.
    local_only_patches = {iid: local_patches[iid] for iid in escalated_ids}
    local_only_resolved = grade_fn("local", local_only_patches) if local_only_patches else {}

    local_resolved: dict[str, bool] = {}
    for inst in instances:
        iid = inst.instance_id
        if escalated_flags[iid]:
            local_resolved[iid] = local_only_resolved.get(iid, False)
        else:
            local_resolved[iid] = final_resolved.get(iid, False)
        per_instance[iid]["resolved"] = final_resolved.get(iid, False)

    n = len(instances)
    escalated_count = len(escalated_ids)
    return {
        "local_arm": local_arm,
        "frontier_arm": frontier_arm,
        "instances": n,
        "escalated": escalated_count,
        "escalation_rate": escalated_count / n if n else 0.0,
        "frontier_empty": frontier_empty,
        "local_pass_at_1": sum(local_resolved.values()) / n if n else 0.0,
        "escalated_pass_at_1": sum(final_resolved.values()) / n if n else 0.0,
        "per_instance": per_instance,
    }
