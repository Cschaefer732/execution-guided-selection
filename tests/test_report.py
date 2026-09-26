from spark_swe_eval.report import render


def test_render_has_caveat_and_rows() -> None:
    md = render(
        [
            {
                "arm": "infinity-high",
                "pass_at_1": 0.4,
                "ci_low": 0.3,
                "ci_high": 0.5,
                "resolved": 8,
                "graded": 20,
                "errors": 0,
            },
            {
                "arm": "infinity-low",
                "pass_at_1": 0.3,
                "ci_low": 0.2,
                "ci_high": 0.4,
                "resolved": 6,
                "graded": 20,
                "errors": 0,
            },
        ],
        subset_size=20,
    )
    assert "infinity-high" in md and "not the official 500" in md.lower()
    assert "reasoning" in md.lower()
