from __future__ import annotations

from math import sqrt


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z * sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def zero_failure_upper_bound(total: int, confidence: float = 0.95) -> float:
    if total <= 0:
        return 1.0
    return 1 - (1 - confidence) ** (1 / total)
