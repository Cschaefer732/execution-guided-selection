"""Eval isolation must actually engage.

CRUSH_GLOBAL_CONFIG is a DIRECTORY — crush joins crush.json onto it. Pointing the guard at a
.json file makes the test fail silently, the export never runs, and the measured agent quietly
inherits whatever skills, MCP servers and tool permissions the interactive agent happens to
have that week. That does not error; it just makes the number mean something else."""

from __future__ import annotations

from spark_swe_eval.agent import build_agent_script
from spark_swe_eval.instances import Instance

INST = Instance("django__django-1", "django/django", "abc123", "Fix the bug", ["t::a"], [], "4.2")


def _isolation_line(script: str) -> str:
    return next(line for line in script.splitlines() if "CRUSH_GLOBAL_CONFIG" in line)


def test_isolation_guard_tests_a_directory_not_a_file() -> None:
    line = _isolation_line(build_agent_script(INST, "nova", "/tmp/wd"))
    assert ' -d "' in line, "guard must be a directory test"
    assert " -f " not in line


def test_isolation_target_is_a_directory_path() -> None:
    line = _isolation_line(build_agent_script(INST, "nova", "/tmp/wd"))
    exported = line.split("CRUSH_GLOBAL_CONFIG=", 1)[1].strip().strip('"')
    assert not exported.endswith(".json"), "crush joins crush.json onto this path itself"
    assert exported.endswith("/.config/crush-eval")


def test_guard_and_export_reference_the_same_path() -> None:
    """A guard that checks one path and exports another is isolation theatre."""
    line = _isolation_line(build_agent_script(INST, "nova", "/tmp/wd"))
    guarded = line.split(" -d ", 1)[1].split("]", 1)[0].strip().strip('"')
    exported = line.split("CRUSH_GLOBAL_CONFIG=", 1)[1].strip().strip('"')
    assert guarded == exported
