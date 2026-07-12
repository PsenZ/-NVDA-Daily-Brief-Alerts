"""Trade attribution: failure taxonomy, grouped statistics and
benchmark-relative metrics over event-backtest trades.

Every grouped row carries the shared statistical discipline
(veyraquant.stats): t statistic on net R, a significance flag that
small samples can never earn, and an explicit insufficient_sample
marker below MIN_STRONG_SAMPLE - "no strong conclusions under 30
trades" is enforced by the data structure, not by good intentions.
"""
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd

from .evaluation import SimTrade
from .stats import MIN_STRONG_SAMPLE, is_significant, mean_stats


# Exit reasons refined by outcome sign: a timeout that made money is a
# different failure mode than one that bled out sideways.
def failure_taxonomy(trades: list[SimTrade]) -> dict[str, int]:
    taxonomy: Counter[str] = Counter()
    for trade in trades:
        reason = trade.exit_reason or "unknown"
        if reason == "timeout_exit":
            if trade.r_net > 0.05:
                reason = "timeout_win"
            elif trade.r_net < -0.05:
                reason = "timeout_loss"
            else:
                reason = "timeout_flat"
        taxonomy[reason] += 1
    return dict(taxonomy)


@dataclass(frozen=True)
class GroupStat:
    key: str
    n: int
    win_rate: Optional[float]
    avg_r: Optional[float]
    total_r: float
    avg_alpha: Optional[float]
    t_stat: Optional[float]
    significant: Optional[bool]
    insufficient_sample: bool


def group_metrics(
    trades: list[SimTrade], key: str | Callable[[SimTrade], str]
) -> list[GroupStat]:
    key_fn = key if callable(key) else (lambda trade: getattr(trade, key, "") or "unknown")
    buckets: dict[str, list[SimTrade]] = {}
    for trade in trades:
        buckets.setdefault(key_fn(trade), []).append(trade)

    stats: list[GroupStat] = []
    for bucket_key in sorted(buckets):
        rows = buckets[bucket_key]
        r_values = [trade.r_net for trade in rows]
        alphas = [trade.alpha for trade in rows if trade.alpha is not None]
        wins = [value for value in r_values if value > 0]
        t_stat, _low, _high = mean_stats(r_values)
        stats.append(
            GroupStat(
                key=bucket_key,
                n=len(rows),
                win_rate=round(len(wins) / len(rows) * 100, 2) if rows else None,
                avg_r=round(sum(r_values) / len(r_values), 3) if r_values else None,
                total_r=round(sum(r_values), 3),
                avg_alpha=round(sum(alphas) / len(alphas), 6) if alphas else None,
                t_stat=t_stat,
                significant=is_significant(t_stat, len(rows)),
                insufficient_sample=len(rows) < MIN_STRONG_SAMPLE,
            )
        )
    return stats


def attach_benchmark_alpha(
    trades: list[SimTrade], benchmark: Optional[pd.DataFrame]
) -> list[SimTrade]:
    """Fill benchmark_return/alpha per closed trade over an
    EXECUTION-CONSISTENT window (R5.5).

    The engine enters at the entry day's OPEN, so the benchmark leg
    starts at the benchmark's open of the same day (falling back to
    close for legacy close-only frames). The benchmark exit matches the
    trade's exit style: gap exits fill at the open, so the benchmark is
    measured at its open too; intrabar/close exits use the close.
    Trades whose dates are missing from the benchmark calendar keep
    None - never approximate with a different window."""
    if benchmark is None or benchmark.empty:
        return trades
    closes = benchmark["Close"]
    opens = benchmark["Open"] if "Open" in benchmark.columns else closes
    for trade in trades:
        if trade.exit_date is None:
            continue
        exit_series = opens if trade.exit_reason in ("gap_stop", "gap_target") else closes
        try:
            bench_entry = float(opens.loc[trade.entry_date])
            bench_exit = float(exit_series.loc[trade.exit_date])
        except KeyError:
            continue
        if bench_entry <= 0 or trade.entry_price <= 0:
            continue
        trade.benchmark_return = round(bench_exit / bench_entry - 1, 6)
        symbol_return = trade.exit_price / trade.entry_price - 1
        trade.alpha = round(symbol_return - trade.benchmark_return, 6)
    return trades


def attribution_report(
    trades: list[SimTrade], benchmark: Optional[pd.DataFrame] = None
) -> dict[str, Any]:
    """The R5 output cuts: setup, regime, sector, data quality, the
    combined setup-in-regime view, and the failure taxonomy."""
    attach_benchmark_alpha(trades, benchmark)
    return {
        "trades": len(trades),
        "taxonomy": failure_taxonomy(trades),
        "by_setup": group_metrics(trades, "setup_type"),
        "by_regime": group_metrics(trades, "market_regime"),
        "by_sector": group_metrics(trades, "sector"),
        "by_data_quality": group_metrics(trades, "data_quality"),
        "by_setup_regime": group_metrics(
            trades,
            lambda t: f"{t.setup_type or 'unknown'} in {t.market_regime or 'unknown'}",
        ),
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [f"trades: {report['trades']}", f"taxonomy: {report['taxonomy']}"]
    for section in ("by_setup", "by_regime", "by_sector", "by_data_quality", "by_setup_regime"):
        lines.append(f"--- {section} ---")
        for row in report[section]:
            guard = " [insufficient sample <30]" if row.insufficient_sample else ""
            sig = "NA" if row.significant is None else ("YES" if row.significant else "no")
            alpha = "NA" if row.avg_alpha is None else f"{row.avg_alpha:+.4f}"
            lines.append(
                f"{row.key}: n={row.n} win={row.win_rate}% avg_r={row.avg_r} "
                f"total_r={row.total_r} avg_alpha={alpha} "
                f"t={'NA' if row.t_stat is None else f'{row.t_stat:+.2f}'} "
                f"significant={sig}{guard}"
            )
    return "\n".join(lines)
