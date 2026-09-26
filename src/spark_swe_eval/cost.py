"""Parse a Crush --debug log for turn count + best-effort token usage."""

from __future__ import annotations

import json


def parse_crush_log(text: str) -> dict:
    turns = 0
    prompt = 0
    completion = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("msg") == "HTTP Request":
            try:
                body = json.loads(rec.get("body", "{}"))
            except ValueError:
                body = {}
            if body.get("model"):
                turns += 1
        usage = rec.get("usage")
        if isinstance(usage, dict):
            prompt += int(usage.get("prompt_tokens", 0))
            completion += int(usage.get("completion_tokens", 0))
    return {"turns": turns, "prompt_tokens": prompt, "completion_tokens": completion}
