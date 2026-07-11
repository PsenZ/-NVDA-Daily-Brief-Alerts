"""Statistical review of the decision log.

Turns logged decisions into evidence: per-bucket mean alpha with a t
statistic and 95% confidence interval, an explicit significance flag,
score-band buckets, and a horizon comparison to test whether the 5-day
holding assumption is actually the best one.
"""
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .jsonl import read_entries
from .memory import HORIZONS


DIMENSIONS = ("setup_type", "action", "rating", "market_regime", "portfolio_decision", "score_band")

# Two-sided 95% critical values of Student's t by degrees of freedom.
_T_TABLE = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
# Below this many resolved samples a "significant" flag would be noise
# even when |t| clears the critical value.
MIN_SAMPLES_FOR_SIGNIFICANCE = 10


@dataclass(frozen=True)
class ReviewSummary:
    dimension: str
    key: str
    count: int
    resolved_count: int
    unresolved_count: int
    avg_5d_return: float | None
    avg_alpha_vs_spy: float | None
    win_rate: float | None
    t_stat: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    significant: bool | None = None


@dataclass(frozen=True)
class HorizonSummary:
    horizon: int
    count: int
    avg_alpha: float | None
    win_rate: float | None
    t_stat: float | None
    significant: bool | None


def build_review_summaries(path: str, dimensions: tuple[str, ...] = DIMENSIONS) -> list[ReviewSummary]:
    entries = read_entries(path)
    summaries: list[ReviewSummary] = []
    for dimension in dimensions:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            key = _bucket_key(dimension, entry)
            buckets.setdefault(key, []).append(entry)
        for key, rows in buckets.items():
            summaries.append(_summarize_bucket(dimension, key, rows))
    return summaries


def build_horizon_summaries(path: str) -> list[HorizonSummary]:
    """Compare outcome horizons on the same resolved decisions."""
    entries = [row for row in read_entries(path) if row.get("outcome_status") == "resolved"]
    summaries: list[HorizonSummary] = []
    for horizon in HORIZONS:
        key = str(horizon)
        alphas = [
            value
            for value in (
                _as_float((row.get("horizon_alphas") or {}).get(key)) for row in entries
            )
            if value is not None
        ]
        t_stat, _low, _high = _mean_stats(alphas)
        wins = [value for value in alphas if value > 0]
        summaries.append(
            HorizonSummary(
                horizon=horizon,
                count=len(alphas),
                avg_alpha=_avg(alphas),
                win_rate=round(len(wins) / len(alphas) * 100, 2) if alphas else None,
                t_stat=t_stat,
                significant=_is_significant(t_stat, len(alphas)),
            )
        )
    return summaries


def brief_review_notes(path: str, limit: int = 2) -> list[str]:
    summaries = build_review_summaries(path, ("setup_type", "portfolio_decision"))
    candidates = [
        item
        for item in summaries
        if item.resolved_count >= 2 and item.avg_alpha_vs_spy is not None
    ]
    candidates.sort(key=lambda item: item.avg_alpha_vs_spy or 0.0, reverse=True)
    notes: list[str] = []
    for item in candidates[:limit]:
        note = (
            f"{item.dimension}:{item.key} avg 5D alpha {item.avg_alpha_vs_spy:+.2%} "
            f"over {item.resolved_count} resolved decision(s)."
        )
        if item.significant:
            note += f" (t={item.t_stat:+.2f}, statistically significant)"
        elif item.t_stat is not None:
            note += f" (t={item.t_stat:+.2f}, n={item.resolved_count}: not significant)"
        else:
            note += f" (n={item.resolved_count}: too few samples for statistics)"
        notes.append(note)
    return notes


def main() -> int:
    path = "memory/decision_log.jsonl"
    for summary in build_review_summaries(path):
        avg_alpha = "NA" if summary.avg_alpha_vs_spy is None else f"{summary.avg_alpha_vs_spy:+.4f}"
        win_rate = "NA" if summary.win_rate is None else f"{summary.win_rate:.2f}%"
        t_stat = "NA" if summary.t_stat is None else f"{summary.t_stat:+.2f}"
        if summary.ci_low is None or summary.ci_high is None:
            ci = "NA"
        else:
            ci = f"[{summary.ci_low:+.4f}, {summary.ci_high:+.4f}]"
        sig = "NA" if summary.significant is None else ("YES" if summary.significant else "no")
        print(
            f"{summary.dimension}={summary.key} count={summary.count} "
            f"resolved={summary.resolved_count} unresolved={summary.unresolved_count} "
            f"avg_alpha_vs_spy={avg_alpha} win_rate={win_rate} "
            f"t={t_stat} ci95={ci} significant={sig}"
        )
    print("--- horizon comparison (alpha vs SPY on the same decisions) ---")
    for horizon in build_horizon_summaries(path):
        avg_alpha = "NA" if horizon.avg_alpha is None else f"{horizon.avg_alpha:+.4f}"
        win_rate = "NA" if horizon.win_rate is None else f"{horizon.win_rate:.2f}%"
        t_stat = "NA" if horizon.t_stat is None else f"{horizon.t_stat:+.2f}"
        sig = "NA" if horizon.significant is None else ("YES" if horizon.significant else "no")
        print(
            f"horizon={horizon.horizon}d n={horizon.count} avg_alpha={avg_alpha} "
            f"win_rate={win_rate} t={t_stat} significant={sig}"
        )
    return 0


def _bucket_key(dimension: str, entry: dict[str, Any]) -> str:
    if dimension == "score_band":
        return _score_band(entry.get("score"))
    return str(entry.get(dimension) or "unknown")


def _score_band(score: Any) -> str:
    value = _as_float(score)
    if value is None:
        return "unknown"
    if value >= 75:
        return "75+"
    if value >= 65:
        return "65-74"
    if value >= 55:
        return "55-64"
    return "<55"


def _summarize_bucket(dimension: str, key: str, rows: list[dict[str, Any]]) -> ReviewSummary:
    resolved = [row for row in rows if row.get("outcome_status") == "resolved"]
    unresolved_count = len([row for row in rows if row.get("outcome_status") != "resolved"])
    returns = [_as_float(row.get("five_day_return")) for row in resolved]
    alphas = [_as_float(row.get("alpha_vs_spy")) for row in resolved]
    returns = [value for value in returns if value is not None]
    alphas = [value for value in alphas if value is not None]
    win_rate = None
    if returns:
        wins = [value for value in returns if value > 0]
        win_rate = round(len(wins) / len(returns) * 100, 2)
    t_stat, ci_low, ci_high = _mean_stats(alphas)
    return ReviewSummary(
        dimension=dimension,
        key=key,
        count=len(rows),
        resolved_count=len(resolved),
        unresolved_count=unresolved_count,
        avg_5d_return=_avg(returns),
        avg_alpha_vs_spy=_avg(alphas),
        win_rate=win_rate,
        t_stat=t_stat,
        ci_low=ci_low,
        ci_high=ci_high,
        significant=_is_significant(t_stat, len(alphas)),
    )


def _mean_stats(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """t statistic (mean != 0) and 95% CI for the mean; None when n < 3
    or the sample has zero variance."""
    n = len(values)
    if n < 3:
        return None, None, None
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    if variance <= 0:
        return None, round(mean, 6), round(mean, 6)
    std_error = sqrt(variance) / sqrt(n)
    critical = _t_critical_95(n - 1)
    return (
        round(mean / std_error, 3),
        round(mean - critical * std_error, 6),
        round(mean + critical * std_error, 6),
    )


def _is_significant(t_stat: float | None, n: int) -> bool | None:
    if t_stat is None:
        return None
    if n < MIN_SAMPLES_FOR_SIGNIFICANCE:
        return False
    return abs(t_stat) >= _t_critical_95(n - 1)


def _t_critical_95(degrees_of_freedom: int) -> float:
    if degrees_of_freedom < 1:
        return float("inf")
    return _T_TABLE.get(degrees_of_freedom, 1.96)


def _as_float(value) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


if __name__ == "__main__":
    raise SystemExit(main())
