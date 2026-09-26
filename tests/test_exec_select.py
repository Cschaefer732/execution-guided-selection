import json
from pathlib import Path

from spark_swe_eval.exec_select import rescore_run, select_by_execution

# psf__requests-1921 shape: 2 identical-and-wrong candidates, 3 diverse-and-correct candidates.
WRONG = "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -1 +1 @@\n-a\n+wrong\n"
RIGHT_A = "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -1 +1 @@\n-a\n+right_a\n"
RIGHT_B = "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -1 +1 @@\n-a\n+right_b\n"
RIGHT_C = "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -1 +1 @@\n-a\n+right_c\n"
PATCHES = [WRONG, WRONG, RIGHT_A, RIGHT_B, RIGHT_C]
RESOLVED = [False, False, True, True, True]


def test_requests_1921_shape_with_regression_picks_a_correct_candidate() -> None:
    # the 2 wrong candidates are identical (majority-vote would pick one of them); regression
    # info says only the 3 correct ones pass PASS_TO_PASS
    regression_ok = [False, False, True, True, True]
    idx = select_by_execution(PATCHES, regression_ok)
    assert RESOLVED[idx] is True


def test_requests_1921_shape_without_regression_degrades_to_vote() -> None:
    # all-None regression -> same as the old diff-vote selector, which picks the 2-vote WRONG
    # cluster over any single 1-vote RIGHT candidate
    regression_ok = [None, None, None, None, None]
    idx = select_by_execution(PATCHES, regression_ok)
    assert idx in (0, 1)
    assert RESOLVED[idx] is False


def test_all_none_regression_never_returns_negative_when_usable_candidates_exist() -> None:
    idx = select_by_execution([RIGHT_A, RIGHT_B], [None, None])
    assert idx >= 0


def test_all_false_regression_still_returns_a_usable_candidate() -> None:
    idx = select_by_execution([RIGHT_A, RIGHT_B, RIGHT_C], [False, False, False])
    assert idx >= 0


def test_empty_or_unusable_candidates_returns_negative_one() -> None:
    assert select_by_execution(["", "   ", "\n"], [True, False, None]) == -1
    assert select_by_execution([], []) == -1


def test_prefers_true_over_false_and_none() -> None:
    idx = select_by_execution([RIGHT_A, RIGHT_B, RIGHT_C], [False, None, True])
    assert idx == 2


def test_tiebreak_within_preferred_set_uses_vote_then_length_then_index() -> None:
    # RIGHT_A and its variant vote together (2) vs RIGHT_C alone (1); all pass regression
    variant_of_a = "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -2 +2 @@\n-a\n+right_a\n"
    patches = [RIGHT_A, variant_of_a, RIGHT_C]
    idx = select_by_execution(patches, [True, True, True])
    assert idx in (0, 1)


def test_leak_guard_no_fail_to_pass_reference() -> None:
    src = Path("src/spark_swe_eval/exec_select.py").read_text()
    assert "fail_to_pass" not in src.lower()


def test_rescore_run_reproduces_vote_numbers_with_no_regression_data(tmp_path) -> None:
    patches = {"inst1": PATCHES}
    bestofn = {
        "arm": "nova",
        "N": 5,
        "instances": 1,
        "per_instance": {"inst1": {"resolved_per_candidate": RESOLVED}},
    }
    (tmp_path / "patches.json").write_text(json.dumps(patches))
    (tmp_path / "bestofn.json").write_text(json.dumps(bestofn))

    out = rescore_run(tmp_path)
    assert out["per_instance"]["inst1"]["selected_index"] in (0, 1)
    assert out["per_instance"]["inst1"]["deployable_resolved"] is False
    assert out["per_instance"]["inst1"]["oracle_resolved"] is True
    assert out["oracle_resolved"] == 1
    assert out["deployable_resolved"] == 0


def test_rescore_run_with_regression_data_flips_deployable(tmp_path) -> None:
    patches = {"inst1": PATCHES}
    bestofn = {
        "arm": "nova",
        "N": 5,
        "instances": 1,
        "per_instance": {"inst1": {"resolved_per_candidate": RESOLVED}},
    }
    (tmp_path / "patches.json").write_text(json.dumps(patches))
    (tmp_path / "bestofn.json").write_text(json.dumps(bestofn))

    regression = {"inst1": [False, False, True, True, True]}
    out = rescore_run(tmp_path, regression)
    assert out["per_instance"]["inst1"]["deployable_resolved"] is True
    assert out["deployable_resolved"] == 1
