import subprocess

import pytest

from spark_swe_eval import exec_select
from spark_swe_eval.exec_select import build_regression_script, run_regression_check
from spark_swe_eval.instances import Instance

INST = Instance(
    instance_id="psf__requests-1921",
    repo="psf/requests",
    base_commit="abc123",
    problem_statement="x",
    fail_to_pass=["tests/test_x.py::test_bug"],
    pass_to_pass=["tests/test_y.py::test_ok"],
    version="1.0",
)


def _stub(monkeypatch, code: int, out: str) -> None:
    monkeypatch.setattr(exec_select, "run", lambda host, script, timeout=None: (code, out, ""))


def test_marker_zero_is_pass(monkeypatch) -> None:
    _stub(monkeypatch, 0, "1 passed in 0.1s\nRESULT_EXIT=0\n")
    assert run_regression_check("h", "/tmp/wd", INST, "p") is True


def test_marker_one_with_real_failure_is_regression(monkeypatch) -> None:
    _stub(monkeypatch, 1, "1 failed, 2 passed in 0.2s\nRESULT_EXIT=1\n")
    assert run_regression_check("h", "/tmp/wd", INST, "p") is False


def test_collection_error_is_infra_not_regression(monkeypatch) -> None:
    # missing deps in a bare clone: pytest reports an error, which must NOT read as a regression
    _stub(
        monkeypatch,
        1,
        "ERROR tests/test_y.py - ModuleNotFoundError: no module named 'urllib3'\nRESULT_EXIT=1\n",
    )
    assert run_regression_check("h", "/tmp/wd", INST, "p") is None


def test_missing_marker_is_infra(monkeypatch) -> None:
    # clone/apply failed before pytest ever ran
    _stub(monkeypatch, 91, "error: patch does not apply\n")
    assert run_regression_check("h", "/tmp/wd", INST, "p") is None


def test_django_style_ids_do_not_yield_a_false_verdict(monkeypatch) -> None:
    # pytest usage error on non-pytest test ids => exit 4, no trustworthy verdict
    _stub(monkeypatch, 4, "ERROR: not found: test_ok (django.tests.T)\nRESULT_EXIT=4\n")
    assert run_regression_check("h", "/tmp/wd", INST, "p") is None


def test_timeout_is_infra(monkeypatch) -> None:
    def boom(host, script, timeout=None):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=1)

    monkeypatch.setattr(exec_select, "run", boom)
    assert run_regression_check("h", "/tmp/wd", INST, "p") is None


def test_empty_pass_to_pass_is_vacuously_true() -> None:
    inst = Instance(**{**INST.__dict__, "pass_to_pass": []})
    assert run_regression_check("h", "/tmp/wd", inst, "p") is True


def test_script_refuses_dangerous_workdir() -> None:
    for wd in ("", "  ", "/", "~", "$HOME"):
        with pytest.raises(ValueError):
            build_regression_script(INST, "p", wd)


def test_script_has_no_recursive_force_delete() -> None:
    assert "rm -rf" not in build_regression_script(INST, "p", "/tmp/wd")
