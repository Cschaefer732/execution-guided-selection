"""The eval can pin a frozen harness snapshot, or measure the deployed one.

Frozen keeps a baseline comparable across months. It also means a frozen run cannot detect a
harness change at all — on 2026-08-18 the frozen config carried 2 hooks on one event while the
live harness carried 24 across ten — so a run made to evaluate harness work must use live.
"""

import pytest

from spark_swe_eval.agent import build_agent_script
from spark_swe_eval.instances import Instance

INST = Instance(
    instance_id="pallets__flask-5014",
    repo="pallets/flask",
    base_commit="deadbeef",
    problem_statement="Fix the thing.",
    fail_to_pass=[],
    pass_to_pass=[],
    version="2.3",
)


def script(**kw) -> str:
    return build_agent_script(INST, "nova", "/tmp/wd", **kw)


def test_frozen_is_the_default_and_pins_the_config():
    s = script()
    assert 'export CRUSH_GLOBAL_CONFIG="$HOME/.config/crush-eval"' in s


def test_live_does_not_pin_the_config():
    s = script(harness="live")
    assert "CRUSH_GLOBAL_CONFIG" not in s.replace(
        "# harness=live: no CRUSH_GLOBAL_CONFIG pin, the deployed harness is under test", ""
    )


def test_live_still_runs_the_same_agent_and_instance():
    s = script(harness="live")
    assert "agent run --model nova" in s
    assert "git checkout --quiet deadbeef" in s


def test_an_unknown_harness_mode_is_rejected_not_silently_treated_as_live():
    with pytest.raises(ValueError, match="frozen"):
        script(harness="livee")


# --- dsh arm: same instances, same model, same grader, different harness -------------


def test_a_dsh_arm_invokes_deepseek_harness_not_the_default_agent():
    s = build_agent_script(INST, "dsh", "/tmp/wd")
    assert "@deepseek-ai/dsh" in s and "--profile headless" in s
    assert "agent run" not in s


def test_a_dsh_arm_carries_the_ollama_patch_and_dsh_home():
    s = build_agent_script(INST, "dsh", "/tmp/wd")
    assert "--patch $HOME/.dsh/ollama.patch.yml" in s
    assert "DSH_HOME=$HOME/.dsh" in s


def test_a_default_agent_arm_is_unchanged_by_the_dsh_branch():
    s = build_agent_script(INST, "nova", "/tmp/wd")
    assert "agent run --model nova" in s
    assert "deepseek" not in s


def test_an_arm_merely_containing_dsh_is_not_treated_as_dsh():
    """Prefix match on the colon-separated head — 'nova-dsh' is a default-agent arm."""
    s = build_agent_script(INST, "nova-dsh", "/tmp/wd")
    assert "agent run --model nova-dsh" in s


def test_an_unregistered_arm_falls_through_to_the_default_agent_verbatim():
    """Historical arm names must keep working — including ones containing a slash."""
    s = build_agent_script(INST, "frontier/claude-opus-4-8", "/tmp/wd")
    assert "agent run --model frontier/claude-opus-4-8" in s


def test_a_model_override_on_a_harness_that_pins_its_model_is_refused():
    """dsh pins its model in the patch overlay, so accepting an override would silently run a
    different model than the arm name claims — the one thing a harness comparison cannot do."""
    with pytest.raises(ValueError, match="would be ignored"):
        build_agent_script(INST, "dsh:qwen3-coder:30b", "/tmp/wd")


def test_openclaude_arm_uses_the_anthropic_endpoint_and_pins_the_model():
    s = build_agent_script(INST, "openclaude", "/tmp/wd")
    assert "@gitlawb/openclaude@latest -p" in s
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:11434" in s
    assert "--model qwen3.8:27b" in s
    assert "--permission-mode bypassPermissions" in s


def test_opencode_arm_prefixes_the_provider_and_bypasses_prompts():
    s = build_agent_script(INST, "opencode", "/tmp/wd")
    assert "opencode-ai@latest run" in s
    assert "--model ollama/qwen3.8:27b" in s
    assert "--auto" in s


def test_every_registered_harness_pins_a_model_somewhere():
    """A harness that inherits a default model silently breaks the comparison."""
    from spark_swe_eval.agent import HARNESS_ARMS

    for name, spec in HARNESS_ARMS.items():
        pinned = "{model}" in spec["template"] or name == "dsh"  # dsh pins in its patch overlay
        assert pinned, f"{name} does not pin a model"
        assert spec["default_model"] == "qwen3.8:27b", f"{name} defaults to a different model"
