from pathlib import Path

from spark_swe_eval.cost import parse_crush_log

LOG = (Path(__file__).parent / "fixtures" / "crush.log").read_text()


def test_counts_turns_and_tokens() -> None:
    c = parse_crush_log(LOG)
    assert c == {"turns": 2, "prompt_tokens": 120, "completion_tokens": 45}


def test_empty_log_is_zeroed() -> None:
    assert parse_crush_log("") == {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0}
