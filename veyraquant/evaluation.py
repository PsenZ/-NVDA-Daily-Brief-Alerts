"""Event-driven portfolio backtester.

Unlike the quick per-symbol scanner in backtest.py, this engine simulates
execution the way the live system actually trades:

- signals form at a bar's close; fills happen at the NEXT bar's open
- an open that gaps through the stop fills at the open (worse than the
  stop), never at the stop price
- when one bar touches both stop and target, the stop is assumed to fill
  first (conservative; never pick the favorable resolution)
- positions are sized off current equity with a per-trade risk fraction,
  capped by max position size and by shared portfolio heat; same-day
  competitors are ranked by score and the later ones get a haircut or
  are skipped when heat runs out
- round-trip cost (config.backtest_cost_bps) is charged in R units via
  backtest.apply_cost; optional slippage_bps moves every fill price
  adversely
- the equity curve is marked to market daily, so drawdowns include open
  positions, not just realized trades

The engine consumes pre-built TradeSignal events and knows nothing about
scoring; R5 wires the live pipeline in as a signal source. Input frames
are expected to be auto-adjusted (splits/dividends), matching DataClient.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from .backtest import apply_cost


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    signal_idx: int          # bar index where the signal formed (at close)
    stop_price: float
    target_price: float
    risk_pct: float          # requested account risk for this trade
    score: float = 0.0       # priority when several signals compete for heat
    # Action semantics (R5.5): "" or BUY_TRIGGER opens a fresh position and
    # is blocked while one is open; ADD_TRIGGER requires an open position.
    action: str = ""
    portfolio_decision: str = ""
    # Attribution tags (R5): carried through to SimTrade for grouping.
    setup_type: str = ""
    market_regime: str = ""
    sector: str = ""
    data_quality: str = ""


@dataclass
class SimTrade:
    symbol: str
    entry_date: Any
    entry_price: float
    stop_price: float
    target_price: float
    shares: float
    risk_pct: float          # allocated (post-haircut) risk
    exit_date: Any = None
    exit_price: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0
    r_gross: float = 0.0
    r_net: float = 0.0
    pnl: float = 0.0
    setup_type: str = ""
    market_regime: str = ""
    sector: str = ""
    data_quality: str = ""
    benchmark_return: Optional[float] = None  # filled by attribution
    alpha: Optional[float] = None


@dataclass
class EventBacktestResult:
    trades: list[SimTrade] = field(default_factory=list)
    equity_curve: list[tuple[Any, float]] = field(default_factory=list)
    starting_equity: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    avg_r: float = 0.0
    avg_r_gross: float = 0.0
    cost_bps: float = 0.0
    skipped_for_heat: int = 0
    cancelled_entries: int = 0
    skipped_duplicate: int = 0   # BUY while a position was already open
    invalid_adds: int = 0        # ADD with no open position to add to


def run_event_backtest(
    frames: dict[str, pd.DataFrame],
    signals: list[TradeSignal],
    config: Any,
    slippage_bps: float = 0.0,
    holding_bars: int = 5,
) -> EventBacktestResult:
    cost_bps = max(0.0, float(getattr(config, "backtest_cost_bps", 0.0)))
    risk_cap = float(getattr(config, "portfolio_heat_max_pct", 3.0))
    max_position_pct = float(getattr(config, "max_position_pct", 10.0))
    starting_equity = float(getattr(config, "account_equity", None) or 100_000.0)
    slip = max(0.0, slippage_bps) / 10_000.0

    # Per-symbol positional indexes and date->index maps.
    index_of: dict[str, dict[Any, int]] = {
        symbol: {ts: i for i, ts in enumerate(frame.index)}
        for symbol, frame in frames.items()
    }
    # Entries scheduled for the bar AFTER the signal bar.
    pending: dict[str, list[TradeSignal]] = {}
    for signal in signals:
        frame = frames.get(signal.symbol)
        if frame is None or signal.signal_idx + 1 >= len(frame):
            continue
        pending.setdefault(signal.symbol, []).append(signal)

    timeline = sorted({ts for frame in frames.values() for ts in frame.index})
    realized_equity = starting_equity
    open_trades: list[SimTrade] = []
    closed: list[SimTrade] = []
    curve: list[tuple[Any, float]] = []
    skipped_for_heat = 0
    cancelled = 0
    skipped_duplicate = 0
    invalid_adds = 0

    def heat_in_use() -> float:
        return sum(trade.risk_pct for trade in open_trades)

    def symbol_is_open(symbol: str) -> bool:
        return any(trade.symbol == symbol for trade in open_trades)

    for ts in timeline:
        # ---- exits first: release heat before new entries compete for it
        still_open: list[SimTrade] = []
        for trade in open_trades:
            frame = frames[trade.symbol]
            idx = index_of[trade.symbol].get(ts)
            if idx is None:
                still_open.append(trade)  # symbol has no bar today
                continue
            bar = frame.iloc[idx]
            trade.bars_held += 1
            exit_price: Optional[float] = None
            reason = ""
            open_px = float(bar["Open"])
            if open_px <= trade.stop_price:
                exit_price, reason = open_px, "gap_stop"      # gap fills at open
            elif open_px >= trade.target_price:
                exit_price, reason = open_px, "gap_target"
            elif float(bar["Low"]) <= trade.stop_price:
                exit_price, reason = trade.stop_price, "stopped_out"  # stop first
            elif float(bar["High"]) >= trade.target_price:
                exit_price, reason = trade.target_price, "target_hit"
            elif trade.bars_held >= holding_bars:
                exit_price, reason = float(bar["Close"]), "timeout_exit"

            if exit_price is None:
                still_open.append(trade)
                continue
            fill = exit_price * (1 - slip)
            risk_per_share = trade.entry_price - trade.stop_price
            trade.exit_date = ts
            trade.exit_price = fill
            trade.exit_reason = reason
            trade.r_gross = (fill - trade.entry_price) / risk_per_share
            trade.r_net = apply_cost(trade.r_gross, trade.entry_price, risk_per_share, cost_bps)
            cost_amount = (trade.r_gross - trade.r_net) * risk_per_share * trade.shares
            trade.pnl = (fill - trade.entry_price) * trade.shares - cost_amount
            realized_equity += trade.pnl
            closed.append(trade)
        open_trades = still_open

        # ---- entries: same-day candidates ranked by score, sharing heat
        candidates: list[TradeSignal] = []
        for symbol, queue in pending.items():
            frame = frames[symbol]
            for signal in queue:
                if frame.index[signal.signal_idx + 1] == ts:
                    candidates.append(signal)
        candidates.sort(key=lambda item: item.score, reverse=True)

        for signal in candidates:
            pending[signal.symbol].remove(signal)
            # Position semantics (R5.5): a fresh BUY never doubles up on an
            # open position; an ADD is only real when there IS a position.
            if signal.action == "ADD_TRIGGER":
                if not symbol_is_open(signal.symbol):
                    invalid_adds += 1
                    continue
            elif symbol_is_open(signal.symbol):
                skipped_duplicate += 1
                continue
            frame = frames[signal.symbol]
            bar = frame.iloc[signal.signal_idx + 1]
            open_px = float(bar["Open"]) * (1 + slip)
            if open_px <= signal.stop_price or open_px >= signal.target_price:
                cancelled += 1  # setup broken or already gone before entry
                continue
            available = risk_cap - heat_in_use()
            allocated = min(signal.risk_pct, available)
            if allocated <= 1e-9:
                skipped_for_heat += 1
                continue
            risk_amount = realized_equity * allocated / 100.0
            risk_per_share = open_px - signal.stop_price
            shares = risk_amount / risk_per_share
            max_value = realized_equity * max_position_pct / 100.0
            if shares * open_px > max_value:
                scale = max_value / (shares * open_px)
                shares *= scale
                allocated *= scale
            trade = SimTrade(
                symbol=signal.symbol,
                entry_date=ts,
                entry_price=open_px,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                shares=shares,
                risk_pct=allocated,
                setup_type=signal.setup_type,
                market_regime=signal.market_regime,
                sector=signal.sector,
                data_quality=signal.data_quality,
            )
            # Worst-case entry-bar handling: if the rest of the entry bar
            # trades through the stop, take the stop TODAY. The target is
            # deliberately NOT granted on the entry bar - when the order of
            # touches is unknowable, always take the adverse resolution.
            if float(bar["Low"]) <= signal.stop_price:
                fill = signal.stop_price * (1 - slip)
                risk_per_share = trade.entry_price - trade.stop_price
                trade.exit_date = ts
                trade.exit_price = fill
                trade.exit_reason = "stopped_out"
                trade.r_gross = (fill - trade.entry_price) / risk_per_share
                trade.r_net = apply_cost(trade.r_gross, trade.entry_price, risk_per_share, cost_bps)
                cost_amount = (trade.r_gross - trade.r_net) * risk_per_share * trade.shares
                trade.pnl = (fill - trade.entry_price) * trade.shares - cost_amount
                realized_equity += trade.pnl
                closed.append(trade)
                continue
            open_trades.append(trade)

        # ---- mark to market
        unrealized = 0.0
        for trade in open_trades:
            frame = frames[trade.symbol]
            idx = index_of[trade.symbol].get(ts)
            last_close = float(frame.iloc[idx]["Close"]) if idx is not None else trade.entry_price
            unrealized += (last_close - trade.entry_price) * trade.shares
        curve.append((ts, realized_equity + unrealized))

    # End-of-test liquidation (R5.5): open positions do not vanish - they
    # are closed at their symbol's last available close so their P&L and
    # costs are real, and the final equity matches the equity curve.
    for trade in open_trades:
        frame = frames[trade.symbol]
        fill = float(frame.iloc[-1]["Close"]) * (1 - slip)
        risk_per_share = trade.entry_price - trade.stop_price
        trade.exit_date = frame.index[-1]
        trade.exit_price = fill
        trade.exit_reason = "end_of_test"
        trade.r_gross = (fill - trade.entry_price) / risk_per_share
        trade.r_net = apply_cost(trade.r_gross, trade.entry_price, risk_per_share, cost_bps)
        cost_amount = (trade.r_gross - trade.r_net) * risk_per_share * trade.shares
        trade.pnl = (fill - trade.entry_price) * trade.shares - cost_amount
        realized_equity += trade.pnl
        closed.append(trade)
    open_trades = []
    if curve:
        curve[-1] = (curve[-1][0], realized_equity)

    return _summarize(closed, curve, starting_equity, realized_equity, cost_bps,
                      skipped_for_heat, cancelled, skipped_duplicate, invalid_adds)


def signals_from_pipeline(
    symbol: str,
    daily: pd.DataFrame,
    config: Any,
    market_histories: dict[str, pd.DataFrame | None] | None = None,
    first_signal_bar: int = 80,
    profile: Any = None,
) -> list[TradeSignal]:
    """Generate TradeSignals by running the REAL analyze pipeline bar by bar.

    Walk-forward evaluation (R5) uses this as the signal source, so the
    engine trades exactly what the live system would have signalled. The
    market filter sees only past benchmark bars (sliced per step); news is
    neutral and fundamentals empty - free history has neither, and that
    limitation is explicit rather than fabricated. first_signal_bar
    confines signals to the evaluation region (train/test isolation)
    while indicators keep their warmup history.
    """
    from .backtest import _market_slice
    from .instruments import default_profile
    from .market import build_market_context
    from .models import FundamentalsData, NewsBundle
    from .signals import analyze_symbol

    prof = profile or default_profile(symbol)
    news = NewsBundle([], [], {"score": 0.0, "label": "中性", "sample_size": 0})
    signals: list[TradeSignal] = []
    for idx in range(max(80, first_signal_bar), len(daily) - 1):
        window = daily.iloc[: idx + 1]
        market = build_market_context(_market_slice(market_histories, window.index[-1]))
        result = analyze_symbol(
            symbol, window, None, FundamentalsData(), None, news, market, config,
            profile=prof,
        )
        if not result.is_actionable:
            continue
        plan = result.trade_plan
        if plan.stop_price is None or plan.target1 is None:
            continue
        signals.append(
            TradeSignal(
                symbol=symbol,
                signal_idx=idx,
                stop_price=float(plan.stop_price),
                target_price=float(plan.target1),
                risk_pct=float(getattr(config, "risk_per_trade_pct", 0.5)),
                score=float(result.score),
                action=getattr(result, "action", ""),
                setup_type=result.setup_type,
                market_regime=result.market_regime,
                sector=result.sector_bucket or prof.sector,
                data_quality=result.data_quality.data_quality_level,
            )
        )
    return signals


def _summarize(
    closed: list[SimTrade],
    curve: list[tuple[Any, float]],
    starting_equity: float,
    realized_equity: float,
    cost_bps: float,
    skipped_for_heat: int,
    cancelled: int,
    skipped_duplicate: int = 0,
    invalid_adds: int = 0,
) -> EventBacktestResult:
    peak = starting_equity
    max_dd = 0.0
    for _ts, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    wins = [trade for trade in closed if trade.r_net > 0]
    return EventBacktestResult(
        trades=closed,
        equity_curve=curve,
        starting_equity=starting_equity,
        final_equity=round(realized_equity, 2),
        total_return_pct=round((realized_equity - starting_equity) / starting_equity * 100, 2),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        avg_r=round(sum(t.r_net for t in closed) / len(closed), 3) if closed else 0.0,
        avg_r_gross=round(sum(t.r_gross for t in closed) / len(closed), 3) if closed else 0.0,
        cost_bps=cost_bps,
        skipped_for_heat=skipped_for_heat,
        cancelled_entries=cancelled,
        skipped_duplicate=skipped_duplicate,
        invalid_adds=invalid_adds,
    )
