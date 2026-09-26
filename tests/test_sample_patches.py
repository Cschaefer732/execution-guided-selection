import spark_swe_eval.agent as agent
from spark_swe_eval.instances import Instance

INST = Instance("django__django-1", "django/django", "abc", "Fix the bug", ["t::a"], [], "4.2")


def test_sample_patches_runs_n_times_with_distinct_workdirs(monkeypatch) -> None:
    calls = []

    def fake_run_agent(instance, arm, host, scaffold, workdir):
        calls.append(workdir)
        return f"patch-{workdir}"

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    patches = agent.sample_patches(INST, "nova", 3, host="h", scaffold="guided")

    assert len(patches) == 3
    assert len(set(calls)) == 3  # distinct workdirs -> independent samples
    assert all(w.endswith(("/s0", "/s1", "/s2")) for w in calls)
