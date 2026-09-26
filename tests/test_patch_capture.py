"""The captured patch must stay applicable.

`run_agent` used to `return diff.strip()`, which removed the trailing newline that every
unified diff requires. `git apply` then failed with "patch unexpectedly ends in middle of
line" -- but ONLY when the final hunk line was a deletion, so most patches applied fine and
the failure read as a flaky grader. It cost openclaude a resolved instance on
django__django-11099, recorded as a harness "error", which silently under-reported
capability. These tests pin the invariant.
"""

import spark_swe_eval.agent as agent
from spark_swe_eval.instances import Instance

INST = Instance("django__django-11099", "django/django", "abc", "Fix it", ["t::a"], [], "4.2")

# Ends on a deletion line -- the exact shape that used to be corrupted.
DIFF_ENDING_IN_DELETION = (
    "diff --git a/x.py b/x.py\n"
    "--- a/x.py\n"
    "+++ b/x.py\n"
    "@@ -1,2 +1,1 @@\n"
    " keep\n"
    "-drop\n"
)


def _capture(monkeypatch, stdout: str) -> str:
    def fake_run(host, script, timeout=None):
        return 0, stdout, ""

    monkeypatch.setattr(agent, "run", fake_run)
    monkeypatch.setattr(agent, "build_agent_script", lambda *a, **k: "noop")
    return agent.run_agent(INST, "nova", host="h", scaffold="guided", workdir="/tmp/w")


def test_a_patch_ending_in_a_deletion_keeps_its_trailing_newline(monkeypatch) -> None:
    assert _capture(monkeypatch, DIFF_ENDING_IN_DELETION).endswith("-drop\n")


def test_capture_does_not_alter_patch_content(monkeypatch) -> None:
    assert _capture(monkeypatch, DIFF_ENDING_IN_DELETION) == DIFF_ENDING_IN_DELETION


def test_a_trailing_newline_is_added_even_when_git_omits_it(monkeypatch) -> None:
    assert _capture(monkeypatch, DIFF_ENDING_IN_DELETION.rstrip("\n")) == DIFF_ENDING_IN_DELETION


def test_exactly_one_trailing_newline_no_matter_how_many_git_emitted(monkeypatch) -> None:
    out = _capture(monkeypatch, DIFF_ENDING_IN_DELETION + "\n\n\n")
    assert out.endswith("-drop\n") and not out.endswith("-drop\n\n")


def test_no_changes_still_yields_an_empty_patch_not_a_bare_newline(monkeypatch) -> None:
    # "" must stay falsy -- an empty-patch check keys off this.
    assert _capture(monkeypatch, "   \n  \n") == ""
