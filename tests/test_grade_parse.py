import json
from pathlib import Path

from spark_swe_eval.grade import Result, parse_report

FIX = json.loads((Path(__file__).parent / "fixtures" / "report.json").read_text())


def test_parse_report_classifies_each_id() -> None:
    results = parse_report(FIX, ["a__a-1", "b__b-2", "c__c-3"], "aurora")
    by_id = {r.instance_id: r for r in results}
    assert by_id["a__a-1"] == Result(
        "a__a-1", "aurora", resolved=True, error=False, unresolved=False
    )
    assert by_id["b__b-2"].unresolved is True and by_id["b__b-2"].resolved is False
    assert by_id["c__c-3"].error is True


def test_absent_id_is_error() -> None:
    (r,) = parse_report(FIX, ["missing__x-9"], "nova")
    assert r.error is True and r.resolved is False


def test_empty_patch_is_unresolved_not_error() -> None:
    (r,) = parse_report(FIX, ["d__d-4"], "aurora")
    assert r.unresolved is True and r.error is False and r.resolved is False
