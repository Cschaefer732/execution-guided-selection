"""Thin SSH helpers — run a script on a remote host over stdin."""

from __future__ import annotations

import subprocess


def run(host: str, script: str, timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", host, "bash -s"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr
