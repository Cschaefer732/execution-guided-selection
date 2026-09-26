from spark_swe_eval.bestofn import (
    Candidate,
    aggregate_instance,
    cluster_key,
    select_candidate,
)

DIFF_A = """diff --git a/m.py b/m.py
index 111..222 100644
--- a/m.py
+++ b/m.py
@@ -10,7 +10,7 @@ def foo():
     x = 1
-    return x
+    return x + 1
"""

# same edit as A but different hunk position, index hash, and surrounding context
DIFF_A_VARIANT = """diff --git a/m.py b/m.py
index 999..aaa 100644
--- a/m.py
+++ b/m.py
@@ -42,6 +42,6 @@ def bar():
     y = 2
-    return x
+    return x + 1
"""

DIFF_B = """diff --git a/m.py b/m.py
index 111..333 100644
--- a/m.py
+++ b/m.py
@@ -10,7 +10,7 @@ def foo():
     x = 1
-    return x
+    return x - 1
"""


def test_cluster_key_ignores_hunk_position_and_hash() -> None:
    assert cluster_key(DIFF_A) == cluster_key(DIFF_A_VARIANT)


def test_cluster_key_distinguishes_different_edits() -> None:
    assert cluster_key(DIFF_A) != cluster_key(DIFF_B)


def test_select_returns_negative_when_all_empty() -> None:
    assert select_candidate(["", "   ", "\n"]) == -1


def test_select_single_nonempty_returns_its_index() -> None:
    assert select_candidate(["", DIFF_A, ""]) == 1


def test_select_majority_cluster_wins() -> None:
    # two votes for the A-edit, one for the B-edit -> pick an A-edit candidate
    idx = select_candidate([DIFF_B, DIFF_A, DIFF_A_VARIANT])
    assert idx in (1, 2)


def test_aggregate_oracle_and_deployable() -> None:
    # candidate 0 (B-edit) is the only resolver, but majority voted for the A-edit ->
    # oracle resolves (someone did), deployable does NOT (selector picked a non-resolver)
    cands = [
        Candidate(patch=DIFF_B, resolved=True),
        Candidate(patch=DIFF_A, resolved=False),
        Candidate(patch=DIFF_A_VARIANT, resolved=False),
    ]
    agg = aggregate_instance(cands)
    assert agg["oracle_resolved"] is True
    assert agg["deployable_resolved"] is False
    assert agg["selected_index"] in (1, 2)


def test_aggregate_all_empty_is_unresolved() -> None:
    cands = [Candidate(patch="", resolved=False), Candidate(patch="  ", resolved=False)]
    agg = aggregate_instance(cands)
    assert agg["oracle_resolved"] is False
    assert agg["deployable_resolved"] is False
    assert agg["selected_index"] == -1


def test_aggregate_selected_index_override() -> None:
    # candidate 0 (B-edit) is the only resolver; an external selector (e.g. execution-based)
    # can override the vote-picked index without changing how oracle is computed
    cands = [
        Candidate(patch=DIFF_B, resolved=True),
        Candidate(patch=DIFF_A, resolved=False),
    ]
    agg = aggregate_instance(cands, selected_index=0)
    assert agg["selected_index"] == 0
    assert agg["deployable_resolved"] is True
    assert agg["oracle_resolved"] is True
