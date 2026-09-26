"""Best-of-N candidate selection.

Two numbers come out of an N-sample run, and they must never be conflated:

* **oracle pass@k** — the instance counts as resolved if ANY of the N candidates passes the
  held-out FAIL_TO_PASS test. This is a CEILING (it peeks at the grader's oracle), not a
  deployable result.
* **deployable best-of-N** — a selector that never sees FAIL_TO_PASS picks ONE candidate; the
  instance counts as resolved only if THAT candidate passes. This is what you could actually ship.

The selector here is Agentless-style majority vote over normalized diffs: cluster candidates by
the edits they make (ignoring hunk position, index hashes, and context), pick a representative of
the largest cluster. No test information enters selection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    patch: str
    resolved: bool


def cluster_key(patch: str) -> str:
    """A canonical key for the set of edits a patch makes.

    Ignores everything that varies between two patches that make the SAME change: index hashes,
    hunk headers / line numbers, and surrounding context lines. Keeps per-file the multiset of
    added/removed content lines (whitespace-normalized), sorted so order doesn't matter.
    """
    current = "?"
    edits: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            # file header, e.g. "+++ b/path" — set the current file, don't treat as an edit
            path = line[4:].strip()
            if path.startswith(("a/", "b/")):
                path = path[2:]
            current = path
            continue
        if line.startswith("diff --git") or line.startswith("index ") or line.startswith("@@"):
            continue
        if line.startswith("+") or line.startswith("-"):
            sign = line[0]
            content = line[1:].strip()
            if content:  # skip pure-whitespace edits
                edits.append(f"{current}\0{sign}{content}")
    return "\n".join(sorted(edits))


def _usable(patch: str) -> bool:
    return bool(cluster_key(patch).strip())


def select_candidate(patches: list[str]) -> int:
    """Index of the chosen candidate, or -1 if none is usable. Never inspects test results.

    Majority vote over `cluster_key`; ties broken toward the shortest patch, then lowest index
    (Occam + determinism)."""
    usable = [(i, p) for i, p in enumerate(patches) if _usable(p)]
    if not usable:
        return -1
    counts = Counter(cluster_key(p) for _, p in usable)
    best_size = max(counts.values())
    winners = [(i, p) for i, p in usable if counts[cluster_key(p)] == best_size]
    winners.sort(key=lambda ip: (len(ip[1]), ip[0]))
    return winners[0][0]


def aggregate_instance(candidates: list[Candidate], selected_index: int | None = None) -> dict:
    """Reduce one instance's N candidates to oracle + deployable resolution.

    `selected_index`, when given, overrides the diff-vote selector (e.g. with an
    execution-based pick from exec_select.select_by_execution) without changing how oracle is
    computed."""
    oracle = any(c.resolved for c in candidates)
    idx = (
        selected_index
        if selected_index is not None
        else select_candidate([c.patch for c in candidates])
    )
    deployable = idx >= 0 and candidates[idx].resolved
    return {
        "oracle_resolved": oracle,
        "deployable_resolved": deployable,
        "selected_index": idx,
        "n_candidates": len(candidates),
    }
