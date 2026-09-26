from spark_swe_eval.exec_select import (
    build_instance_report_script,
    regression_from_instance_report,
)

IID = "psf__requests-1921"


def _report(success: list[str], failure: list[str], f2p_failure: list[str] | None = None) -> dict:
    return {
        IID: {
            "tests_status": {
                "PASS_TO_PASS": {"success": success, "failure": failure},
                "FAIL_TO_PASS": {"success": [], "failure": f2p_failure or []},
            }
        }
    }


def test_all_pass_to_pass_succeed() -> None:
    assert regression_from_instance_report(_report(["a", "b"], [])) is True


def test_any_pass_to_pass_failure_is_a_regression() -> None:
    assert regression_from_instance_report(_report(["a"], ["b"])) is False


def test_fail_to_pass_does_not_affect_the_verdict() -> None:
    # the held-out tests failing must NOT make this look like a regression
    passing = _report(["a", "b"], [], f2p_failure=["held_out_test"])
    assert regression_from_instance_report(passing) is True


def test_empty_or_missing_sections_are_unknown() -> None:
    assert regression_from_instance_report({}) is None
    assert regression_from_instance_report({IID: {}}) is None
    assert regression_from_instance_report(_report([], [])) is None


def test_unkeyed_report_shape_is_accepted() -> None:
    inner = _report(["a"], [])[IID]
    assert regression_from_instance_report(inner) is True


def test_report_script_targets_the_run_evaluation_tree() -> None:
    script = build_instance_report_script("run1", "nova", IID, "~/swe-grade")
    assert "logs/run_evaluation/run1/nova/" in script
    assert IID in script
    assert "report.json" in script
