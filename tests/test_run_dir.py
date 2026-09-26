from pathlib import Path

from spark_swe_eval.cli import already_done, run_dir


def test_run_dir_created(tmp_path: Path) -> None:
    d = run_dir(tmp_path, "aurora", "20260723-1200")
    assert d.exists() and d.name == "aurora-20260723-1200"


def test_already_done_reads_trace_ids(tmp_path: Path) -> None:
    d = run_dir(tmp_path, "nova", "t")
    (d / "traces.jsonl").write_text('{"instance_id":"a__a-1"}\n{"instance_id":"b__b-2"}\n')
    assert already_done(d) == {"a__a-1", "b__b-2"}
