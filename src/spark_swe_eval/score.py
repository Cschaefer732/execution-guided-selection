"""Aggregate Results into pass@1 with bootstrap CIs."""

from __future__ import annotations

import random

from spark_swe_eval.grade import Result


def _gradable(results: list[Result]) -> list[Result]:
    return [r for r in results if not r.error]


def pass_at_1(results: list[Result]) -> float:
    gradable = _gradable(results)
    if not gradable:
        return 0.0
    return sum(r.resolved for r in gradable) / len(gradable)


def bootstrap_ci(results: list[Result], iters: int = 1000, seed: int = 0) -> tuple[float, float]:
    gradable = _gradable(results)
    if not gradable:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(gradable)
    means: list[float] = []
    for _ in range(iters):
        sample = [gradable[rng.randrange(n)].resolved for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return (means[int(0.025 * iters)], means[int(0.975 * iters)])


def arm_summary(results: list[Result]) -> dict:
    gradable = _gradable(results)
    low, high = bootstrap_ci(results)
    return {
        "arm": results[0].arm if results else "?",
        "n": len(results),
        "graded": len(gradable),
        "resolved": sum(r.resolved for r in gradable),
        "errors": sum(r.error for r in results),
        "pass_at_1": pass_at_1(results),
        "ci_low": low,
        "ci_high": high,
    }
