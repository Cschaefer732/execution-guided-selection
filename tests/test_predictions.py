import json
from pathlib import Path

from spark_swe_eval.predictions import prediction_line, write_predictions


def test_prediction_line_shape() -> None:
    assert prediction_line("x__y-1", "aurora", "diff --git a b") == {
        "instance_id": "x__y-1",
        "model_name_or_path": "aurora",
        "model_patch": "diff --git a b",
    }


def test_write_predictions_is_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "preds.jsonl"
    write_predictions([prediction_line("a", "nova", "d1"), prediction_line("b", "nova", "d2")], p)
    lines = p.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["instance_id"] == "a"
