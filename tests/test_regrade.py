import json

from spark_swe_eval import cli
from spark_swe_eval.regrade import regrade_export


def _report(resolved: bool) -> dict:
    return {"resolved": resolved, "tests_status": {"PASS_TO_PASS": {"success": [], "failure": []}}}


def test_regrade_export_recovers_from_bestofn_json_resolved_per_candidate(tmp_path) -> None:
    d = tmp_path / "nova-bestofn-tsA"
    d.mkdir()
    patches = {"inst1": ["p0", "p1", "p2"]}
    bestofn = {
        "arm": "nova",
        "N": 3,
        "per_instance": {
            "inst1": {"n_candidates": 3, "resolved_per_candidate": [True, False, True]}
        },
    }
    (d / "patches.json").write_text(json.dumps(patches))
    (d / "bestofn.json").write_text(json.dumps(bestofn))

    grades, unrecoverable = regrade_export(d)

    assert grades == {"inst1#0": True, "inst1#1": False, "inst1#2": True}
    assert unrecoverable == []


def test_regrade_export_falls_back_to_fabricated_swebench_report_logs(tmp_path) -> None:
    # run dir name encodes arm + ts, matching run_dir()'s "{arm}-bestofn-{ts}" scheme
    d = tmp_path / "nova-bestofn-tsB"
    d.mkdir()
    patches = {"inst1": ["p0", "p1"], "inst2": ["q0", "q1"]}
    # old-schema bestofn.json: aggregate only, no resolved_per_candidate for either instance
    bestofn = {
        "arm": "nova",
        "N": 2,
        "per_instance": {
            "inst1": {"n_candidates": 2},
            "inst2": {"n_candidates": 2},
        },
    }
    (d / "patches.json").write_text(json.dumps(patches))
    (d / "bestofn.json").write_text(json.dumps(bestofn))

    # inst1: both slots have a fabricated report.json (fully recoverable)
    for k, resolved in enumerate([True, False]):
        p = d / "logs" / "run_evaluation" / f"nova-bo{k}-tsB" / "nova" / "inst1" / "report.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_report(resolved)))

    # inst2: only slot 0 has a report; slot 1 is missing -> instance stays unrecoverable
    p2 = d / "logs" / "run_evaluation" / "nova-bo0-tsB" / "nova" / "inst2" / "report.json"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text(json.dumps(_report(True)))

    grades, unrecoverable = regrade_export(d)

    assert grades == {"inst1#0": True, "inst1#1": False}
    assert unrecoverable == ["inst2"]
    # partial evidence for inst2 must not leak a guessed key into the map
    assert "inst2#0" not in grades
    assert "inst2#1" not in grades


def test_regrade_export_is_honest_on_a_run_dir_with_no_recoverable_evidence(tmp_path) -> None:
    # mirrors runs/nova-bestofn-demo2: only the old aggregate-only bestofn.json survives,
    # no patches.json, no logs/ -- nothing to reconstruct per-candidate grades from.
    d = tmp_path / "nova-bestofn-demo2"
    d.mkdir()
    bestofn = {
        "arm": "nova",
        "N": 5,
        "per_instance": {
            "django__django-11099": {"n_candidates": 5},
            "pallets__flask-5014": {"n_candidates": 5},
        },
    }
    (d / "bestofn.json").write_text(json.dumps(bestofn))

    grades, unrecoverable = regrade_export(d)

    assert grades == {}
    assert sorted(unrecoverable) == ["django__django-11099", "pallets__flask-5014"]


def test_regrade_export_on_a_completely_empty_run_dir_reports_nothing_to_guess_from(
    tmp_path,
) -> None:
    d = tmp_path / "empty-bestofn-tsZ"
    d.mkdir()

    grades, unrecoverable = regrade_export(d)

    assert grades == {}
    assert unrecoverable == []


def test_regrade_export_cmd_writes_candidate_grades_json_as_the_bare_map(tmp_path) -> None:
    patches = {"inst1": ["p0"]}
    bestofn = {
        "arm": "nova",
        "N": 1,
        "per_instance": {"inst1": {"n_candidates": 1, "resolved_per_candidate": [True]}},
    }
    (tmp_path / "patches.json").write_text(json.dumps(patches))
    (tmp_path / "bestofn.json").write_text(json.dumps(bestofn))

    out = cli.regrade_export_cmd(tmp_path)

    assert out["candidate_grades"] == {"inst1#0": True}
    assert out["unrecoverable_instances"] == []
    assert json.loads((tmp_path / "candidate_grades.json").read_text()) == {"inst1#0": True}
