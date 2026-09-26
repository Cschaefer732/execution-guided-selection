import json

from spark_swe_eval import cli
from spark_swe_eval.grade import Result
from spark_swe_eval.instances import Instance
from spark_swe_eval.phase2 import per_candidate_grades

INST_A = Instance(
    instance_id="a__a-1",
    repo="a/a",
    base_commit="deadbeef",
    problem_statement="fix it",
    fail_to_pass=["tests/test_x.py::test_hidden"],
    pass_to_pass=[],
    version="1.0",
)
INST_B = Instance(
    instance_id="b__b-2",
    repo="b/b",
    base_commit="feedbead",
    problem_statement="fix it too",
    fail_to_pass=["tests/test_y.py::test_hidden"],
    pass_to_pass=[],
    version="1.0",
)


def test_per_candidate_grades_flattens_resolved_lists_with_index_aligned_keys() -> None:
    per_instance = {
        "inst1": {"resolved_per_candidate": [True, False, True]},
        "inst2": {"resolved_per_candidate": [False]},
    }
    assert per_candidate_grades(per_instance) == {
        "inst1#0": True,
        "inst1#1": False,
        "inst1#2": True,
        "inst2#0": False,
    }


def test_run_bestofn_arm_persists_candidate_grades_json(tmp_path, monkeypatch) -> None:
    # patches per (instance, slot): a__a-1 resolves on slots 0 and 2; b__b-2 never resolves.
    patches_by_slot = {
        "a__a-1": ["patchA0", "patchA1", "patchA2"],
        "b__b-2": ["patchB0", "patchB1", "patchB2"],
    }
    resolved_by_slot = {
        "a__a-1": [True, False, True],
        "b__b-2": [False, False, False],
    }

    monkeypatch.setattr(cli, "load_instances", lambda ids: [INST_A, INST_B])

    def fake_sample_patches(instance, arm, n, host, scaffold):
        return patches_by_slot[instance.instance_id]

    monkeypatch.setattr(cli, "sample_patches", fake_sample_patches)

    def fake_run_grader(preds_path, run_id, ids, host, arm, max_workers, workdir):
        k = int(run_id.rsplit("-bo", 1)[1].split("-")[0])
        return [
            Result(
                iid,
                arm,
                resolved=resolved_by_slot[iid][k],
                error=False,
                unresolved=not resolved_by_slot[iid][k],
            )
            for iid in ids
        ]

    monkeypatch.setattr(cli, "run_grader", fake_run_grader)

    subset_path = tmp_path / "subset.txt"
    subset_path.write_text("a__a-1\nb__b-2\n")

    out = cli.run_bestofn_arm(
        "nova",
        subset_path,
        "host-agent",
        "host-grader",
        3,
        "ts1",
        base=tmp_path,
    )

    d = tmp_path / "runs" / "nova-bestofn-ts1"
    assert (d / "candidate_grades.json").exists()
    grades = json.loads((d / "candidate_grades.json").read_text())
    assert grades == {
        "a__a-1#0": True,
        "a__a-1#1": False,
        "a__a-1#2": True,
        "b__b-2#0": False,
        "b__b-2#1": False,
        "b__b-2#2": False,
    }
    # keys line up with patches.json's candidate order (candidate_idx = list index)
    saved_patches = json.loads((d / "patches.json").read_text())
    for iid, ps in saved_patches.items():
        for k in range(len(ps)):
            assert f"{iid}#{k}" in grades
    assert grades == per_candidate_grades(out["per_instance"])
