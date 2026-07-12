from dataclasses import dataclass

import pandas as pd

from .config import AppConfig
from .market import build_market_context
from .models import FundamentalsData, NewsBundle
from .signals import analyze_symbol


@dataclass
class BacktestResult:
    trades: int
    win_rate: float
    avg_r: float
    max_drawdown_pct: float
    buy_hold_pct: float
    avg_r_gross: float = 0.0
    cost_bps: float = 0.0


def run_backtest(
    symbol: str,
    daily: pd.DataFrame,
    config: AppConfig,
    market_histories: dict[str, pd.DataFrame | None] | None = None,
    first_signal_bar: int = 80,
) -> BacktestResult:
    """Backtest one symbol.

    market_histories should hold real benchmark frames (e.g. SPY/QQQ/SMH/^VIX);
    each is sliced to the walk-forward window date so the market filter sees
    only past benchmark data. When omitted, a neutral market context is used
    instead of the old (invalid) behavior of feeding the symbol's own prices
    in as the benchmarks.

    first_signal_bar lets walk-forward evaluation restrict signals to a
    validation region while still giving indicators their warmup history.
    Per-trade round-trip cost (config.backtest_cost_bps) is deducted from
    every outcome; avg_r is net, avg_r_gross keeps the frictionless number.
    """
    cost_bps = max(0.0, float(getattr(config, "backtest_cost_bps", 0.0)))
    if len(daily) < 90:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0, cost_bps=cost_bps)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    outcomes: list[float] = []
    gross_outcomes: list[float] = []
    news = NewsBundle([], [], {"score": 0.0, "label": "中性", "sample_size": 0})

    for idx in range(max(80, first_signal_bar), len(daily) - 6):
        window = daily.iloc[: idx + 1]
        market = build_market_context(
            _market_slice(market_histories, window.index[-1])
        )
        result = analyze_symbol(
            symbol,
            window,
            None,
            FundamentalsData(),
            None,
            news,
            market,
            config,
        )
        # Structural fields only (R3.5): decisions must never depend on
        # display strings or localized signal_type text.
        if not result.is_actionable:
            continue
        plan = result.trade_plan
        if plan.stop_price is None or plan.target1 is None:
            continue

        entry = float(daily["Close"].iloc[idx + 1])
        stop = float(plan.stop_price)
        target = float(plan.target1)
        future = daily.iloc[idx + 2 : idx + 7]
        outcome_r = 0.0
        risk = max(entry - stop, 1e-9)
        # Same-bar ambiguity is resolved pessimistically: when a bar's range
        # touches both the stop and the target, the stop is assumed to fill
        # first, so results are a worst-case rather than a best-case read.
        for _, row in future.iterrows():
            if float(row["Low"]) <= stop:
                outcome_r = -1.0
                break
            if float(row["High"]) >= target:
                outcome_r = (target - entry) / risk
                break
        else:
            outcome_r = (float(future["Close"].iloc[-1]) - entry) / risk

        gross_outcomes.append(outcome_r)
        net_r = apply_cost(outcome_r, entry, risk, cost_bps)
        outcomes.append(net_r)
        equity *= 1 + net_r * config.risk_per_trade_pct / 100
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    if not outcomes:
        buy_hold = (daily["Close"].iloc[-1] - daily["Close"].iloc[0]) / daily["Close"].iloc[0] * 100
        return BacktestResult(0, 0.0, 0.0, 0.0, round(float(buy_hold), 2), cost_bps=cost_bps)

    wins = [item for item in outcomes if item > 0]
    buy_hold = (daily["Close"].iloc[-1] - daily["Close"].iloc[0]) / daily["Close"].iloc[0] * 100
    return BacktestResult(
        trades=len(outcomes),
        win_rate=round(len(wins) / len(outcomes) * 100, 2),
        avg_r=round(sum(outcomes) / len(outcomes), 2),
        max_drawdown_pct=round(max_drawdown, 2),
        buy_hold_pct=round(float(buy_hold), 2),
        avg_r_gross=round(sum(gross_outcomes) / len(gross_outcomes), 2),
        cost_bps=cost_bps,
    )


def apply_cost(outcome_r: float, entry: float, risk_per_share: float, cost_bps: float) -> float:
    """Deduct a round-trip cost (spread + slippage, in bps of entry price),
    expressed in R units so it scales with how tight the stop is."""
    if cost_bps <= 0 or entry <= 0 or risk_per_share <= 0:
        return outcome_r
    cost_r = (entry * cost_bps / 10_000) / risk_per_share
    return outcome_r - cost_r


def _market_slice(
    market_histories: dict[str, pd.DataFrame | None] | None,
    as_of,
) -> dict[str, pd.DataFrame | None]:
    if not market_histories:
        return {}
    sliced: dict[str, pd.DataFrame | None] = {}
    for name, frame in market_histories.items():
        if frame is None or frame.empty:
            sliced[name] = None
            continue
        sliced[name] = frame.loc[frame.index <= as_of]
    return sliced


