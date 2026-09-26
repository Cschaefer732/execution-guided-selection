"""Per-arm agent wall clock.

Decode on GB10 is memory-bandwidth-bound, so a 120B MoE gets through far fewer tokens per
second than a 30B. Running an escalation target on the local arm's budget measures its
timeout instead of its reasoning — gpt-oss already produced empty patches on 2/3 of an N=3
subset that way, which looks identical to a capability failure."""

from __future__ import annotations

import spark_swe_eval.agent as agent_mod
from spark_swe_eval.agent import DEFAULT_AGENT_TIMEOUT, build_agent_script, run_agent
from spark_swe_eval.cli import make_escalation_sample_fn
from spark_swe_eval.instances import Instance

INST = Instance("django__django-1", "django/django", "abc123", "Fix the bug", ["t::a"], [], "4.2")


def test_script_uses_the_default_budget_when_unspecified() -> None:
    assert f"timeout {DEFAULT_AGENT_TIMEOUT} " in build_agent_script(INST, "nova", "/tmp/wd")


def test_script_honours_a_longer_budget() -> None:
    s = build_agent_script(INST, "infinity", "/tmp/wd", timeout_s=2400)
    assert "timeout 2400 " in s
    assert f"timeout {DEFAULT_AGENT_TIMEOUT} " not in s


def _capture_run(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_run(host, script, timeout):
        calls.append({"host": host, "script": script, "timeout": timeout})
        return 0, "", ""

    monkeypatch.setattr(agent_mod, "run", fake_run)
    return calls


def test_ssh_outlasts_the_agent_timeout(monkeypatch) -> None:
    """An ssh timeout at or below the agent's own kills the run before the patch lands."""
    calls = _capture_run(monkeypatch)
    run_agent(INST, "infinity", timeout_s=2400)
    agent_call = calls[0]
    assert "timeout 2400 " in agent_call["script"]
    assert agent_call["timeout"] > 2400


def test_escalation_gives_each_arm_its_own_budget(monkeypatch) -> None:
    calls = _capture_run(monkeypatch)
    sample_fn = make_escalation_sample_fn(
        {INST.instance_id: INST}, "test-agent-host", {"nova": 1200, "infinity": 2400}
    )
    sample_fn(INST.instance_id, "nova")
    sample_fn(INST.instance_id, "infinity")
    agent_scripts = [c["script"] for c in calls if "agent run" in c["script"]]
    assert "timeout 1200 " in agent_scripts[0] and "--model nova" in agent_scripts[0]
    assert "timeout 2400 " in agent_scripts[1] and "--model infinity" in agent_scripts[1]


def test_unlisted_arm_falls_back_to_the_default(monkeypatch) -> None:
    calls = _capture_run(monkeypatch)
    sample_fn = make_escalation_sample_fn(
        {INST.instance_id: INST}, "test-agent-host", {"nova": 1200}
    )
    sample_fn(INST.instance_id, "opus5")
    script = next(c["script"] for c in calls if "agent run" in c["script"])
    assert f"timeout {DEFAULT_AGENT_TIMEOUT} " in script
