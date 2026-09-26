from spark_swe_eval.grade import _report_name, build_grade_script


def test_build_grade_script_gold_and_ids() -> None:
    s = build_grade_script(
        "gold", "m0gold", ["a__a-1", "b__b-2"], "princeton-nlp/SWE-bench_Verified"
    )
    assert "run_evaluation" in s and "--predictions_path gold" in s
    assert "a__a-1" in s and "b__b-2" in s and "--run_id m0gold" in s


def test_build_grade_script_file_predictions() -> None:
    s = build_grade_script("/tmp/p.jsonl", "r1", ["a__a-1"], "princeton-nlp/SWE-bench_Verified")
    assert "--predictions_path /tmp/p.jsonl" in s and "--run_id r1" in s


def test_report_name_gold_and_arm() -> None:
    assert _report_name("gold", "rid") == "gold.rid.json"
    assert _report_name("aurora", "rid") == "aurora.rid.json"
