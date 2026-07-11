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


def run_backtest(
    symbol: str,
    daily: pd.DataFrame,
    config: AppConfig,
    market_histories: dict[str, pd.DataFrame | None] | None = None,
) -> BacktestResult:
    """Backtest one symbol.

    market_histories should hold real benchmark frames (e.g. SPY/QQQ/SMH/^VIX);
    each is sliced to the walk-forward window date so the market filter sees
    only past benchmark data. When omitted, a neutral market context is used
    instead of the old (invalid) behavior of feeding the symbol's own prices
    in as the benchmarks.
    """
    if len(daily) < 90:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    outcomes: list[float] = []
    news = NewsBundle([], [], {"score": 0.0, "label": "中性", "sample_size": 0})

    for idx in range(80, len(daily) - 6):
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
        if result.signal_type not in {"突破入场", "趋势回踩加仓"}:
            continue

        entry = float(daily["Close"].iloc[idx + 1])
        stop = _money_to_float(result.stop)
        target = _money_to_float(result.targets.split("/")[0])
        future = daily.iloc[idx + 2 : idx + 7]
        outcome_r = 0.0
        risk = max(entry - stop, 1e-9)
        for _, row in future.iterrows():
            if float(row["Low"]) <= stop:
                outcome_r = -1.0
                break
            if float(row["High"]) >= target:
                outcome_r = (target - entry) / risk
                break
        else:
            outcome_r = (float(future["Close"].iloc[-1]) - entry) / risk

        outcomes.append(outcome_r)
        equity *= 1 + outcome_r * config.risk_per_trade_pct / 100
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    if not outcomes:
        buy_hold = (daily["Close"].iloc[-1] - daily["Close"].iloc[0]) / daily["Close"].iloc[0] * 100
        return BacktestResult(0, 0.0, 0.0, 0.0, round(float(buy_hold), 2))

    wins = [item for item in outcomes if item > 0]
    buy_hold = (daily["Close"].iloc[-1] - daily["Close"].iloc[0]) / daily["Close"].iloc[0] * 100
    return BacktestResult(
        trades=len(outcomes),
        win_rate=round(len(wins) / len(outcomes) * 100, 2),
        avg_r=round(sum(outcomes) / len(outcomes), 2),
        max_drawdown_pct=round(max_drawdown, 2),
        buy_hold_pct=round(float(buy_hold), 2),
    )


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


def _money_to_float(value: str) -> float:
    return float(value.replace("$", "").replace(",", "").strip())
