from spark_swe_eval.cli import m0_verdict


def test_m0_verdict_ok() -> None:
    assert m0_verdict(0.95, 0.0)["ok"] is True


def test_m0_verdict_fails_on_low_gold() -> None:
    assert m0_verdict(0.6, 0.0)["ok"] is False


def test_m0_verdict_fails_on_high_empty() -> None:
    assert m0_verdict(1.0, 0.4)["ok"] is False
