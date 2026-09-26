from pathlib import Path

from spark_swe_eval.escalate import run_escalation, should_escalate
from spark_swe_eval.instances import Instance

FIX = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-a\n+b\n"
ALT = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-a\n+c\n"


def _inst(iid: str) -> Instance:
    return Instance(
        instance_id=iid,
        repo="a/a",
        base_commit="deadbeef",
        problem_statement="fix it",
        fail_to_pass=["tests/test_x.py::test_hidden"],
        pass_to_pass=["tests/test_x.py::test_existing"],
        version="1.0",
    )


# --- should_escalate truth table -------------------------------------------------------------


def test_should_escalate_empty_patch_always_escalates() -> None:
    assert should_escalate("", True, escalate_on_unknown=True) is True
    assert should_escalate("   \n", False, escalate_on_unknown=False) is True


def test_should_escalate_regression_false_escalates() -> None:
    assert should_escalate(FIX, False) is True


def test_should_escalate_regression_true_does_not_escalate() -> None:
    assert should_escalate(FIX, True) is False


def test_should_escalate_regression_none_follows_policy_flag() -> None:
    assert should_escalate(FIX, None, escalate_on_unknown=True) is True
    assert should_escalate(FIX, None, escalate_on_unknown=False) is False


# --- run_escalation -----------------------------------------------------------------------------


def test_empty_local_patch_always_escalates() -> None:
    instances = [_inst("i1")]

    def sample_fn(iid: str, arm: str) -> str:
        return "" if arm == "local" else FIX

    def regression_fn(iid: str, patch: str) -> bool | None:
        return True  # would normally NOT escalate, but the patch is empty

    def grade_fn(label: str, preds: dict) -> dict:
        return {iid: patch == FIX for iid, patch in preds.items()}

    out = run_escalation(instances, "local", "frontier", sample_fn, regression_fn, grade_fn)
    assert out["escalated"] == 1
    assert out["per_instance"]["i1"]["escalated"] is True
    assert out["per_instance"]["i1"]["resolved"] is True


def test_frontier_empty_patch_falls_back_to_local_and_counted() -> None:
    instances = [_inst("i1")]

    def sample_fn(iid: str, arm: str) -> str:
        return FIX if arm == "local" else ""  # frontier comes back empty (e.g. out of credits)

    def regression_fn(iid: str, patch: str) -> bool | None:
        return False  # force escalation despite a usable local patch

    def grade_fn(label: str, preds: dict) -> dict:
        return {iid: patch == FIX for iid, patch in preds.items()}

    out = run_escalation(instances, "local", "frontier", sample_fn, regression_fn, grade_fn)
    assert out["frontier_empty"] == 1
    assert out["per_instance"]["i1"]["frontier_usable"] is False
    # final patch fell back to the (usable) local patch -> still resolves
    assert out["per_instance"]["i1"]["resolved"] is True
    assert out["escalated_pass_at_1"] == 1.0


def test_passing_regression_does_not_escalate_and_never_calls_frontier() -> None:
    instances = [_inst("i1")]
    frontier_calls: list[str] = []

    def sample_fn(iid: str, arm: str) -> str:
        if arm == "frontier":
            frontier_calls.append(iid)
        return FIX

    def regression_fn(iid: str, patch: str) -> bool | None:
        return True

    def grade_fn(label: str, preds: dict) -> dict:
        return {iid: True for iid in preds}

    out = run_escalation(instances, "local", "frontier", sample_fn, regression_fn, grade_fn)
    assert out["per_instance"]["i1"]["escalated"] is False
    assert frontier_calls == []


def test_escalation_rate_and_counts() -> None:
    instances = [_inst("i1"), _inst("i2"), _inst("i3"), _inst("i4")]

    def sample_fn(iid: str, arm: str) -> str:
        return FIX

    def regression_fn(iid: str, patch: str) -> bool | None:
        # i1, i2 escalate (regression False); i3, i4 don't (regression True)
        return iid not in {"i1", "i2"}

    def grade_fn(label: str, preds: dict) -> dict:
        return {iid: True for iid in preds}

    out = run_escalation(instances, "local", "frontier", sample_fn, regression_fn, grade_fn)
    assert out["escalated"] == 2
    assert out["instances"] == 4
    assert out["escalation_rate"] == 0.5


def test_local_pass_at_1_uses_local_only_grading_for_escalated_instances() -> None:
    instances = [_inst("i1")]

    def sample_fn(iid: str, arm: str) -> str:
        return FIX if arm == "local" else ALT  # frontier gives a different (worse) patch

    def regression_fn(iid: str, patch: str) -> bool | None:
        return False  # force escalation

    def grade_fn(label: str, preds: dict) -> dict:
        # local resolves, frontier (ALT) doesn't
        return {iid: patch == FIX for iid, patch in preds.items()}

    out = run_escalation(instances, "local", "frontier", sample_fn, regression_fn, grade_fn)
    assert out["local_pass_at_1"] == 1.0  # local-only baseline: FIX resolves
    assert out["escalated_pass_at_1"] == 0.0  # final (frontier ALT) does not resolve


def test_leak_guard_no_fail_to_pass_reference() -> None:
    src = Path("src/spark_swe_eval/escalate.py").read_text()
    assert "fail_to_pass" not in src.lower()
