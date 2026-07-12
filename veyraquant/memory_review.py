"""Statistical review of the decision log.

Turns logged decisions into evidence: per-bucket mean alpha with a t
statistic and 95% confidence interval, an explicit significance flag,
score-band buckets, and a horizon comparison to test whether the 5-day
holding assumption is actually the best one.
"""
from dataclasses import dataclass
from typing import Any

from .jsonl import read_entries
from .memory import HORIZONS
from .stats import is_significant as _is_significant_shared
from .stats import mean_stats as _mean_stats_shared


DIMENSIONS = ("setup_type", "action", "rating", "market_regime", "portfolio_decision", "score_band")

# Statistics are shared with trade attribution via veyraquant.stats.


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
    return _mean_stats_shared(values)


def _is_significant(t_stat: float | None, n: int) -> bool | None:
    return _is_significant_shared(t_stat, n)


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
