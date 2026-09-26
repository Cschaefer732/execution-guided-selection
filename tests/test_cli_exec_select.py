import json

import spark_swe_eval.cli as cli
from spark_swe_eval.instances import Instance

INST = Instance(
    instance_id="a__a-1",
    repo="a/a",
    base_commit="deadbeef",
    problem_statement="fix it",
    fail_to_pass=["tests/test_x.py::test_hidden"],
    pass_to_pass=["tests/test_x.py::test_existing"],
    version="1.0",
)


def test_make_regression_fn_calls_run_regression_check_per_candidate(monkeypatch) -> None:
    seen = []

    def fake_check(host, workdir, instance, patch):
        seen.append((host, workdir, instance.instance_id, patch))
        return True

    monkeypatch.setattr(cli, "run_regression_check", fake_check)
    regression_fn = cli.make_regression_fn({"a__a-1": INST}, "test-grader-host")
    out = regression_fn(2, {"a__a-1": "diff --git a/x b/x"})

    assert out == {"a__a-1": True}
    assert seen[0][0] == "test-grader-host"
    assert seen[0][2] == "a__a-1"
    assert "s2" in seen[0][1]  # slot index threaded into the workdir, distinct per sample


def test_rescore_cmd_writes_rescored_json(tmp_path) -> None:
    patches = {"a__a-1": ["diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"]}
    bestofn = {
        "arm": "nova",
        "N": 1,
        "instances": 1,
        "per_instance": {"a__a-1": {"resolved_per_candidate": [True]}},
    }
    (tmp_path / "patches.json").write_text(json.dumps(patches))
    (tmp_path / "bestofn.json").write_text(json.dumps(bestofn))

    out = cli.rescore_cmd(tmp_path, None)

    assert out["deployable_resolved"] == 1
    assert (tmp_path / "rescored.json").exists()
    assert json.loads((tmp_path / "rescored.json").read_text()) == out
