from pathlib import Path

from spark_swe_eval.instances import read_subset, Instance, _to_instance


def test_read_subset_skips_comments_and_blanks(tmp_path: Path) -> None:
    p = tmp_path / "subset.txt"
    p.write_text("# header\n\nastropy__astropy-12907\n  django__django-11099  \n")
    assert read_subset(p) == ["astropy__astropy-12907", "django__django-11099"]


def test_to_instance_parses_json_list_fields() -> None:
    row = {
        "instance_id": "x__y-1",
        "repo": "x/y",
        "base_commit": "abc",
        "problem_statement": "boom",
        "version": "1.0",
        "FAIL_TO_PASS": '["t::a", "t::b"]',
        "PASS_TO_PASS": '["t::c"]',
    }
    inst = _to_instance(row)
    assert inst == Instance("x__y-1", "x/y", "abc", "boom", ["t::a", "t::b"], ["t::c"], "1.0")
