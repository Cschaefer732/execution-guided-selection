import spark_swe_eval.cli as cli
from spark_swe_eval.grade import Result


def test_make_grade_fn_maps_results_and_uses_slot_runid(monkeypatch) -> None:
    seen = {}

    def fake_run_grader(preds_path, run_id, ids, host, arm, max_workers, workdir):
        seen["run_id"] = run_id
        seen["host"] = host
        seen["max_workers"] = max_workers
        seen["workdir"] = workdir
        return [
            Result("a__a-1", arm, resolved=True, error=False, unresolved=False),
            Result("b__b-2", arm, resolved=False, error=False, unresolved=True),
        ]

    monkeypatch.setattr(cli, "run_grader", fake_run_grader)
    grade_fn = cli.make_grade_fn(
        "nova", "test-grader-host", "ts9", max_workers=1, workdir="~/swe-grade-arm"
    )
    out = grade_fn(2, {"a__a-1": "patchA", "b__b-2": ""})

    assert out == {"a__a-1": True, "b__b-2": False}
    assert seen["run_id"] == "nova-bo2-ts9"  # unique per sample slot -> no swebench short-circuit
    assert seen["host"] == "test-grader-host"
    assert seen["max_workers"] == 1 and seen["workdir"] == "~/swe-grade-arm"
