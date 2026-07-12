"""Shared statistical helpers: t statistics, confidence intervals and
significance flags, used by the decision-log review and trade attribution.

No scipy: two-sided 95% critical values come from a small Student's t
table (df 1-30, then the normal 1.96)."""
from math import sqrt
from typing import Optional

T_TABLE_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

# Below this many samples a "significant" flag would be noise even when
# |t| clears the critical value.
MIN_SAMPLES_FOR_SIGNIFICANCE = 10
# Below this many samples no strong conclusion of any kind is allowed.
MIN_STRONG_SAMPLE = 30


def t_critical_95(degrees_of_freedom: int) -> float:
    if degrees_of_freedom < 1:
        return float("inf")
    return T_TABLE_95.get(degrees_of_freedom, 1.96)


def mean_stats(values: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(t statistic for mean != 0, 95% CI low, CI high); Nones when n < 3
    or the sample has zero variance."""
    n = len(values)
    if n < 3:
        return None, None, None
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    if variance <= 0:
        return None, round(mean, 6), round(mean, 6)
    std_error = sqrt(variance) / sqrt(n)
    critical = t_critical_95(n - 1)
    return (
        round(mean / std_error, 3),
        round(mean - critical * std_error, 6),
        round(mean + critical * std_error, 6),
    )


def is_significant(t_stat: Optional[float], n: int) -> Optional[bool]:
    if t_stat is None:
        return None
    if n < MIN_SAMPLES_FOR_SIGNIFICANCE:
        return False
    return abs(t_stat) >= t_critical_95(n - 1)
