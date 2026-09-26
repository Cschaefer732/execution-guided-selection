from spark_swe_eval.grade import Result
from spark_swe_eval.score import arm_summary, pass_at_1


def _r(iid: str, resolved: bool, error: bool = False) -> Result:
    return Result(
        iid, "aurora", resolved=resolved, error=error, unresolved=not resolved and not error
    )


def test_pass_at_1_ignores_errors() -> None:
    rs = [_r("a", True), _r("b", False), _r("c", False, error=True)]
    assert pass_at_1(rs) == 0.5  # 1 resolved of 2 gradable


def test_pass_at_1_empty_is_zero() -> None:
    assert pass_at_1([_r("a", False, error=True)]) == 0.0


def test_arm_summary_counts() -> None:
    s = arm_summary([_r("a", True), _r("b", False)])
    assert (
        s["arm"] == "aurora" and s["graded"] == 2 and s["resolved"] == 1 and s["pass_at_1"] == 0.5
    )
