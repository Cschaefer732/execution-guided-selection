from spark_swe_eval.agent import build_agent_script
from spark_swe_eval.instances import Instance

INST = Instance("django__django-1", "django/django", "abc123", "Fix the bug", ["t::a"], [], "4.2")


def test_build_agent_script_clones_checks_out_runs() -> None:
    s = build_agent_script(INST, "aurora", "/tmp/wd")
    assert "git clone" in s and "django/django" in s and "abc123" in s
    assert "--model aurora" in s and "agent run" in s


def test_build_agent_script_quotes_workdir_and_prompt() -> None:
    s = build_agent_script(INST, "nova", "/tmp/wd")
    assert "/tmp/wd" in s and "rm -rf" in s and "git checkout --quiet abc123" in s


def test_guided_scaffold_adds_reproduce_verify_and_never_leaks_gold_test() -> None:
    s = build_agent_script(INST, "aurora", "/tmp/wd", scaffold="guided")
    low = s.lower()
    assert "reproduce" in low and "verify" in low
    # the held-out FAIL_TO_PASS test id must NEVER reach the agent prompt (that is the oracle)
    assert "t::a" not in s


def test_bare_scaffold_is_default_and_unchanged() -> None:
    assert build_agent_script(INST, "aurora", "/tmp/wd") == build_agent_script(
        INST, "aurora", "/tmp/wd", scaffold="bare"
    )


def test_script_sources_frontier_env_guarded_for_api_arms() -> None:
    s = build_agent_script(INST, "opus48", "/tmp/wd")
    # guarded source so the key reaches crush over non-interactive ssh, no-op if absent
    assert "[ -f ~/.config/swe-eval/frontier.env ]" in s
    assert "set -a" in s and "frontier.env" in s
    assert "--model opus48" in s
    # the source must run before the agent
    assert s.index("frontier.env") < s.index("agent run")


def test_script_pins_frozen_eval_config() -> None:
    # eval runs must use the frozen config so interactive skill/MCP changes can't leak in.
    # CRUSH_GLOBAL_CONFIG is a directory (crush appends crush.json); asserting a .json path
    # here is what let the export sit broken and unnoticed. See test_eval_isolation.py.
    s = build_agent_script(INST, "nova", "/tmp/wd")
    assert "CRUSH_GLOBAL_CONFIG" in s and "crush-eval" in s and "crush-eval.json" not in s
    assert s.index("CRUSH_GLOBAL_CONFIG") < s.index("agent run")
