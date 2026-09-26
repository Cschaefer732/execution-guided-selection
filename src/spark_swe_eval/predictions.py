"""Assemble a swebench predictions JSONL from agent patches."""

from __future__ import annotations

import json
from pathlib import Path


def prediction_line(instance_id: str, arm: str, patch: str) -> dict:
    return {"instance_id": instance_id, "model_name_or_path": arm, "model_patch": patch}


def write_predictions(rows: list[dict], path: Path) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
