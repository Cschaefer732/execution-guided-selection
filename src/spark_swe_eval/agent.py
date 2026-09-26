"""Run the coding agent over SSH and capture its candidate patch."""

from __future__ import annotations

import os
import shlex
import sys

from spark_swe_eval.instances import Instance
from spark_swe_eval.remote import run

# Host running the agent under test, and the command that invokes it. Both are BYO: point
# AGENT_HOST at your GPU/inference box and AGENT_CMD at whatever CLI runs your local-model
# agent there (installed on that host's PATH). Defaults assume everything runs on localhost.
AGENT_HOST = os.environ.get("AGENT_HOST", "localhost")
AGENT_CMD = os.environ.get("AGENT_CMD", "agent")


_BARE = "Fix the issue described above by editing the code in this repository. Do not modify test files."

# Non-leaky execution-feedback scaffold (reproduce -> fix -> verify -> iterate). Never references
# the held-out FAIL_TO_PASS test — the agent must find/write its own reproduction. Research shows
# this reproduce-and-verify loop disproportionately helps smaller models.
_GUIDED = (
    "You are in the repository root. Fix the issue described above by editing the non-test source.\n"
    "1. Explore the repo to find the code responsible.\n"
    "2. Reproduce the bug — write a small script or use the existing test suite to confirm the "
    "failure BEFORE fixing.\n"
    "3. Make the smallest change that fixes the root cause.\n"
    "4. Verify — re-run your reproduction and nearby existing tests; iterate until they pass.\n"
    "Do not modify existing test files. Keep the change minimal."
)


DEFAULT_AGENT_TIMEOUT = 1200


def build_agent_script(
    instance: Instance,
    arm: str,
    workdir: str,
    scaffold: str = "bare",
    timeout_s: int = DEFAULT_AGENT_TIMEOUT,
    harness: str = "frozen",
) -> str:
    guidance = _GUIDED if scaffold == "guided" else _BARE
    prompt = f"{instance.problem_statement}\n\n{guidance}"
    q = shlex.quote(prompt)
    wd = shlex.quote(workdir)
    # Frontier arms (e.g. frontier/claude-opus-4-8) need ANTHROPIC_API_KEY in env; the
    # non-interactive `ssh host bash -s` shell sources no rc, so export it here. No-op for
    # local ollama arms and for hosts without the file.
    # harness="frozen" (default) pins CRUSH_GLOBAL_CONFIG to the frozen eval config so
    # interactive-agent skill/MCP additions can never leak into a measured run, keeping the
    # pass@1 baseline reproducible. It is a DIRECTORY — crush joins crush.json onto it
    # (config.GlobalConfig); pointing it at a .json file silently disables isolation, since the
    # guard just fails and the run inherits the live config.
    #
    # That isolation has a cost worth naming: the frozen config is a SNAPSHOT of the harness.
    # As of 2026-08-18 it dates from 2026-07-28 and registers 2 hooks on one event, where the
    # live harness registers 24 across ten and confines commands in a sandbox. So a "frozen" run
    # measures the MODEL against an old harness, and is structurally incapable of detecting a
    # harness change — which is exactly what you want to measure when you have just changed the
    # harness. harness="live" drops the pin and runs whatever is actually deployed.
    #
    # Keep the default frozen: a baseline you can compare across months is the more common need,
    # and a live run is not comparable to earlier numbers.
    if harness not in ("frozen", "live"):
        raise ValueError(f"harness must be 'frozen' or 'live', got {harness!r}")
    pin = (
        '[ -d "$HOME/.config/crush-eval" ] && export CRUSH_GLOBAL_CONFIG="$HOME/.config/crush-eval"'
        if harness == "frozen"
        else "# harness=live: no CRUSH_GLOBAL_CONFIG pin, the deployed harness is under test"
    )
    return f"""[ -f ~/.config/swe-eval/frontier.env ] && {{ set -a; . ~/.config/swe-eval/frontier.env; set +a; }}
{pin}
rm -rf {wd} 2>/dev/null || true
git clone --quiet https://github.com/{instance.repo}.git {wd}
cd {wd}
git checkout --quiet {instance.base_commit}
{_agent_invocation(arm, timeout_s, q)} || true
"""


# One entry per harness under test. An arm name is "<harness>" or "<harness>:<model>"; the
# colon-head selects the template and the tail, when present, overrides the model. Everything
# that is not a registered harness is a model tier for the default agent (AGENT_CMD), which
# keeps every historical arm name ("nova", "infinity", "frontier/claude-opus-4-8") working
# untouched.
#
# A template is a shell fragment. {timeout} {model} {prompt} are substituted; {prompt} arrives
# already shell-quoted. Comparing harnesses only means anything if the model and the instance
# are held fixed, so each template must pin the model explicitly rather than inherit a default.
HARNESS_ARMS: dict[str, dict[str, str]] = {
    # DeepSeek Harness. The repo names ollama nowhere, and the shipped headless profile pins
    # its model in `agent-default-model` behind a nested include that settings.yaml cannot
    # reach — only a --patch overlay, applied after the profile layer, can re-pin it. The
    # patch file on the box also carries baseURL -> ollama's /v1. Verified 2026-08-18.
    "dsh": {
        "default_model": "qwen3.8:27b",
        "template": (
            "DSH_HOME=$HOME/.dsh DEEPSEEK_API_KEY=ollama "
            "timeout {timeout} npx -y @deepseek-ai/dsh@latest "
            "--profile headless --patch $HOME/.dsh/ollama.patch.yml {prompt}"
        ),
    },
    # openclaude (Gitlawb/openclaude): a TypeScript Claude Code fork, so it speaks the
    # ANTHROPIC wire format rather than OpenAI. ollama >= 0.14 serves /v1/messages natively
    # (verified on the box: a raw curl to :11434/v1/messages returned a well-formed Anthropic
    # response for qwen3.8:27b), so ANTHROPIC_BASE_URL at ollama's root is all it needs.
    # NOTE the local clone at ~/dev/openclaude is ~4 months stale (HEAD 2026-04-08,
    # package.json 0.1.8) against npm 0.28.0 — pin @latest here, not the clone.
    "openclaude": {
        "default_model": "qwen3.8:27b",
        "template": (
            "ANTHROPIC_BASE_URL=http://127.0.0.1:11434 ANTHROPIC_API_KEY=ollama "
            "timeout {timeout} npx -y @gitlawb/openclaude@latest -p "
            "--model {model} --permission-mode bypassPermissions {prompt}"
        ),
    },
    # opencode (sst/opencode, npm opencode-ai). Its ollama provider is declared globally in
    # ~/.config/opencode/opencode.json via @ai-sdk/openai-compatible, because each eval
    # workdir is a fresh git clone that would wipe a project-level config. Models are
    # addressed provider/model, hence the ollama/ prefix. --auto is its permission bypass.
    "opencode": {
        "default_model": "qwen3.8:27b",
        "template": (
            "timeout {timeout} npx -y opencode-ai@latest run --model ollama/{model} --auto {prompt}"
        ),
    },
}

DEFAULT_AGENT_TEMPLATE = "timeout {timeout} " + AGENT_CMD + " run --model {model} {prompt}"


def _agent_invocation(arm: str, timeout_s: int, quoted_prompt: str) -> str:
    head, _, tail = arm.partition(":")
    spec = HARNESS_ARMS.get(head)
    if spec is None:
        # Not a registered harness -> a model tier for the default agent, passed through verbatim.
        return DEFAULT_AGENT_TEMPLATE.format(timeout=timeout_s, model=arm, prompt=quoted_prompt)
    # A harness whose template does not interpolate {model} pins its model elsewhere (dsh does
    # it in the patch overlay). Accepting "dsh:some-model" there would silently run a different
    # model than the arm name claims, and the whole point of these arms is that the model is
    # held fixed — so refuse instead of quietly ignoring it.
    if tail and "{model}" not in spec["template"]:
        raise ValueError(
            f"arm {arm!r}: the {head!r} harness pins its model outside the command "
            f"({spec['default_model']}), so a ':{tail}' override would be ignored. "
            f"Change that harness's own config, or use arm {head!r} alone."
        )
    model = tail or spec["default_model"]
    return spec["template"].format(timeout=timeout_s, model=model, prompt=quoted_prompt)


def run_agent(
    instance: Instance,
    arm: str,
    host: str = AGENT_HOST,
    scaffold: str = "bare",
    workdir: str | None = None,
    timeout_s: int = DEFAULT_AGENT_TIMEOUT,
    harness: str = "frozen",
) -> str:
    """Run the agent, then capture its diff over a SEPARATE ssh — doing the diff in the
    same shell as the agent races its own process/timeout-kill and drops the patch.

    `timeout_s` is per-arm on purpose: decode on GB10 is memory-bandwidth-bound, so a 120B
    MoE gets through far fewer tokens per second than a 30B. Giving both the same wall clock
    measures the slower model's timeout, not its capability — gpt-oss already produced empty
    patches on 2/3 of an N=3 subset that way."""
    workdir = workdir or f"/tmp/swe/{arm}/{instance.instance_id}"
    # ssh must outlast the agent's own timeout, or it kills the run before the patch lands
    run(
        host,
        build_agent_script(instance, arm, workdir, scaffold, timeout_s, harness),
        timeout=timeout_s + 500,
    )
    _, diff, _ = run(host, f"cd {shlex.quote(workdir)} && git --no-pager diff", timeout=120)
    # A unified diff MUST end in a newline. `.strip()` alone ate it, and `git apply` then
    # rejected the patch with "patch unexpectedly ends in middle of line" -- but only when
    # the final hunk line was a deletion, so most patches survived and the bug looked like
    # a flaky grader. It cost openclaude a resolved instance on django-11099, scored as a
    # harness "error", i.e. it silently under-reported capability. Strip surrounding
    # whitespace (so "no changes" stays falsy) but restore exactly one trailing newline.
    patch = diff.strip()
    return patch + "\n" if patch else ""


def sample_patches(
    instance: Instance,
    arm: str,
    n: int,
    host: str = AGENT_HOST,
    scaffold: str = "bare",
) -> list[str]:
    """Draw N independent candidate patches for one instance (best-of-N).

    Each sample gets its own workdir so a fresh clone + independent agent run produces diversity
    (crush exposes no temperature/seed flag, so we rely on the model's default sampling stochasticity
    across independent runs). Runs are serial — they share the one warm local model on the agent host."""
    patches: list[str] = []
    for k in range(n):
        wd = f"/tmp/swe/{arm}/{instance.instance_id}/s{k}"
        patch = run_agent(instance, arm, host=host, scaffold=scaffold, workdir=wd)
        patches.append(patch)
        print(
            f"[sample] {instance.instance_id} {arm} s{k}: {len(patch)} chars",
            file=sys.stderr,
            flush=True,
        )
    return patches
