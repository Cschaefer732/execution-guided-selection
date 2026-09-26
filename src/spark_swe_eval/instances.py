"""Load SWE-bench Verified instances and filter to a curated subset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    version: str


def read_subset(path: Path) -> list[str]:
    ids: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            ids.append(s)
    return ids


def _to_instance(row: dict) -> Instance:
    def _list(v: object) -> list[str]:
        return json.loads(v) if isinstance(v, str) else list(v)  # HF stores as JSON string

    return Instance(
        instance_id=row["instance_id"],
        repo=row["repo"],
        base_commit=row["base_commit"],
        problem_statement=row["problem_statement"],
        fail_to_pass=_list(row["FAIL_TO_PASS"]),
        pass_to_pass=_list(row["PASS_TO_PASS"]),
        version=str(row["version"]),
    )


def load_instances(
    subset_ids: list[str], dataset: str = "princeton-nlp/SWE-bench_Verified"
) -> list[Instance]:
    from datasets import load_dataset

    rows = {r["instance_id"]: r for r in load_dataset(dataset, split="test")}
    missing = [i for i in subset_ids if i not in rows]
    if missing:
        raise KeyError(f"instance_ids not in {dataset}: {missing}")
    return [_to_instance(rows[i]) for i in subset_ids]
