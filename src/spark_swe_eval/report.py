"""Render the arm-comparison report."""

from __future__ import annotations


def render(summaries: list[dict], subset_size: int) -> str:
    lines = [
        "# spark-swe-eval — Phase 1 results",
        "",
        f"**Subset:** N={subset_size} curated SWE-bench Verified instances "
        "(arm64-runnable bias) — not the official 500, not leaderboard-comparable.",
        "",
        "| arm | pass@1 | 95% CI | resolved/graded | errors |",
        "|---|---|---|---|---|",
    ]
    by_arm = {s["arm"]: s for s in summaries}
    for s in summaries:
        lines.append(
            f"| {s['arm']} | {s['pass_at_1']:.1%} | "
            f"[{s['ci_low']:.1%}, {s['ci_high']:.1%}] | "
            f"{s['resolved']}/{s['graded']} | {s['errors']} |"
        )
    hi, lo = by_arm.get("infinity-high"), by_arm.get("infinity-low")
    if hi and lo:
        delta = hi["pass_at_1"] - lo["pass_at_1"]
        lines += [
            "",
            f"**reasoning=high verdict:** high−low = {delta:+.1%} pass@1 "
            f"({hi['pass_at_1']:.1%} vs {lo['pass_at_1']:.1%}) on this subset.",
        ]
    return "\n".join(lines) + "\n"
