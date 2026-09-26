from spark_swe_eval.phase2 import run_bestofn

# two instances, N=3. Patches chosen so the majority-vote selector and the oracle diverge.
FIX = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-a\n+b\n"
ALT = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-a\n+c\n"

PATCHES = {
    # inst1: two ALT (majority) + one FIX. Only FIX resolves -> oracle YES, deployable NO.
    "inst1": [ALT, ALT, FIX],
    # inst2: two FIX (majority, and they resolve) + one ALT -> oracle YES, deployable YES.
    "inst2": [FIX, FIX, ALT],
}
# resolved-ness per (instance, patch-content): FIX resolves inst1 and inst2; ALT never resolves.
RESOLVES = {"inst1": {FIX}, "inst2": {FIX}}


def sample_fn(iid: str) -> list[str]:
    return PATCHES[iid]


def grade_fn(k: int, preds: dict) -> dict:
    return {iid: patch in RESOLVES[iid] for iid, patch in preds.items()}


def test_run_bestofn_reports_oracle_and_deployable() -> None:
    out = run_bestofn(["inst1", "inst2"], "nova", 3, sample_fn, grade_fn)
    assert out["instances"] == 2
    # both instances have a resolving candidate -> oracle ceiling = 2/2
    assert out["oracle_resolved"] == 2
    assert out["oracle_pass_at_k"] == 1.0
    # deployable: inst2 majority-votes the resolving FIX (yes); inst1 majority-votes ALT (no) -> 1/2
    assert out["deployable_resolved"] == 1
    assert out["deployable_pass_at_1"] == 0.5
    assert out["per_instance"]["inst1"]["oracle_resolved"] is True
    assert out["per_instance"]["inst1"]["deployable_resolved"] is False
    assert out["per_instance"]["inst2"]["deployable_resolved"] is True
    # single-sample baseline: inst1 resolves 1/3, inst2 resolves 2/3 -> 3/6 = 0.5
    assert out["single_sample_pass_at_1"] == 0.5
    assert out["per_instance"]["inst1"]["resolved_per_candidate"] == [False, False, True]
    assert out["per_instance"]["inst2"]["resolved_per_candidate"] == [True, True, False]


def test_run_bestofn_grades_each_slot_once() -> None:
    seen_slots = []

    def counting_grade(k: int, preds: dict) -> dict:
        seen_slots.append(k)
        return {iid: False for iid in preds}

    run_bestofn(["inst1"], "nova", 3, sample_fn, counting_grade)
    assert seen_slots == [0, 1, 2]  # one grading pass per sample slot


def test_run_bestofn_select_fn_overrides_vote() -> None:
    # inst1's vote picks ALT (non-resolving); force-select the resolving FIX candidate instead
    def select_fix(patches: list[str], _regression_ok: list) -> int:
        return patches.index(FIX)

    out = run_bestofn(["inst1"], "nova", 3, sample_fn, grade_fn, select_fn=select_fix)
    assert out["per_instance"]["inst1"]["deployable_resolved"] is True


def test_run_bestofn_regression_fn_feeds_select_fn() -> None:
    seen: list[dict] = []

    def regression_fn(k: int, preds: dict) -> dict:
        seen.append(dict(preds))
        return {iid: (patch == FIX) for iid, patch in preds.items()}

    def select_by_regression(patches: list[str], regression_ok: list) -> int:
        for i, ok in enumerate(regression_ok):
            if ok:
                return i
        return 0

    out = run_bestofn(
        ["inst1"],
        "nova",
        3,
        sample_fn,
        grade_fn,
        regression_fn=regression_fn,
        select_fn=select_by_regression,
    )
    assert len(seen) == 3  # one regression pass per sample slot
    assert out["per_instance"]["inst1"]["deployable_resolved"] is True
