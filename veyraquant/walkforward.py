"""Walk-forward threshold tuning and out-of-sample edge measurement.

Grid-searches StrategyConfig thresholds on a training window, evaluates
the chosen thresholds on the following unseen validation window, then
rolls forward. Only thresholds are tuned (small parameter count keeps
overfitting risk bounded); scoring weights stay fixed. Every number is
net of the backtest cost model, and the summary refuses to claim edge
on thin validation samples.
"""
import logging
from dataclasses import dataclass, replace
from itertools import product
from typing import Any, Optional

import pandas as pd

from .config import AppConfig, StrategyConfig
from .evaluation import run_event_backtest, signals_from_pipeline

logger = logging.getLogger(__name__)

# Deliberately small: 3 thresholds that dominate setup classification.
DEFAULT_GRID: dict[str, list[Any]] = {
    "breakout_score_offset": [-5, 0, 5],
    "breakout_vol_ratio_5_min": [1.5, 2.0, 2.5],
    "pullback_vol_ratio_5_max": [0.6, 0.7],
}
# Below this many pooled validation trades, no verdict is allowed.
MIN_VALIDATION_TRADES = 30


@dataclass(frozen=True)
class FoldResult:
    fold: int
    train_start: int
    train_end: int
    valid_end: int
    best_params: Optional[dict[str, Any]]
    train_avg_r: Optional[float]
    train_trades: int
    valid_avg_r: Optional[float]
    valid_trades: int
    baseline_valid_avg_r: float
    baseline_valid_trades: int


def _evaluate(
    symbol: str,
    frame_slice: pd.DataFrame,
    config: AppConfig,
    market_histories: dict[str, pd.DataFrame | None] | None,
    first_signal_bar: int = 80,
):
    """Run the event engine on signals from the real pipeline (R5)."""
    signals = signals_from_pipeline(
        symbol, frame_slice, config, market_histories, first_signal_bar
    )
    return run_event_backtest({symbol: frame_slice}, signals, config)


def walk_forward(
    symbol: str,
    daily: pd.DataFrame,
    config: AppConfig,
    market_histories: dict[str, pd.DataFrame | None] | None = None,
    param_grid: dict[str, list[Any]] | None = None,
    train_bars: int = 250,
    valid_bars: int = 60,
    step_bars: int | None = None,
    warmup_bars: int = 100,
    min_train_trades: int = 5,
    trade_sink: list | None = None,
) -> list[FoldResult]:
    """Rolling tune/validate on the event-driven engine.

    trade_sink, when provided, collects every tuned-validation SimTrade
    (with attribution tags) for failure-taxonomy and grouped analysis.
    """
    grid = param_grid if param_grid is not None else DEFAULT_GRID
    combos = _grid_combos(grid)
    step = step_bars or valid_bars
    baseline_strategy = StrategyConfig()
    folds: list[FoldResult] = []

    fold_index = 0
    train_start = 0
    while train_start + train_bars + valid_bars <= len(daily):
        train_end = train_start + train_bars
        valid_end = train_end + valid_bars
        train_slice = daily.iloc[train_start:train_end]
        # The validation slice carries warmup history for the indicators,
        # but first_signal_bar confines actual signals to the unseen region.
        valid_slice = daily.iloc[max(0, train_end - warmup_bars) : valid_end]

        best_params: Optional[dict[str, Any]] = None
        best_train: Optional[Any] = None
        for combo in combos:
            candidate = _with_strategy(config, combo)
            outcome = _evaluate(symbol, train_slice, candidate, market_histories)
            if len(outcome.trades) < min_train_trades:
                continue
            if best_train is None or outcome.avg_r > best_train.avg_r:
                best_train = outcome
                best_params = combo

        baseline_valid = _evaluate(
            symbol,
            valid_slice,
            _with_strategy(config, {}, strategy=baseline_strategy),
            market_histories,
            first_signal_bar=warmup_bars,
        )

        if best_params is None:
            folds.append(
                FoldResult(
                    fold=fold_index,
                    train_start=train_start,
                    train_end=train_end,
                    valid_end=valid_end,
                    best_params=None,
                    train_avg_r=None,
                    train_trades=0,
                    valid_avg_r=None,
                    valid_trades=0,
                    baseline_valid_avg_r=baseline_valid.avg_r,
                    baseline_valid_trades=len(baseline_valid.trades),
                )
            )
        else:
            tuned_valid = _evaluate(
                symbol,
                valid_slice,
                _with_strategy(config, best_params),
                market_histories,
                first_signal_bar=warmup_bars,
            )
            if trade_sink is not None:
                trade_sink.extend(tuned_valid.trades)
            folds.append(
                FoldResult(
                    fold=fold_index,
                    train_start=train_start,
                    train_end=train_end,
                    valid_end=valid_end,
                    best_params=best_params,
                    train_avg_r=best_train.avg_r,
                    train_trades=len(best_train.trades),
                    valid_avg_r=tuned_valid.avg_r,
                    valid_trades=len(tuned_valid.trades),
                    baseline_valid_avg_r=baseline_valid.avg_r,
                    baseline_valid_trades=len(baseline_valid.trades),
                )
            )

        fold_index += 1
        train_start += step
    return folds


def summarize(folds: list[FoldResult]) -> dict[str, Any]:
    """Pool validation results across folds into an honest verdict."""
    tuned_r = _pooled_r(
        [(f.valid_avg_r, f.valid_trades) for f in folds if f.valid_avg_r is not None]
    )
    tuned_trades = sum(f.valid_trades for f in folds)
    baseline_r = _pooled_r([(f.baseline_valid_avg_r, f.baseline_valid_trades) for f in folds])
    baseline_trades = sum(f.baseline_valid_trades for f in folds)

    if tuned_trades < MIN_VALIDATION_TRADES:
        verdict = (
            f"insufficient evidence: only {tuned_trades} pooled validation trade(s) "
            f"(need >= {MIN_VALIDATION_TRADES}); no edge claim can be made either way"
        )
    elif tuned_r is not None and tuned_r > 0:
        verdict = f"tuned thresholds show positive out-of-sample net R ({tuned_r:+.2f})"
    else:
        verdict = "no out-of-sample edge demonstrated (pooled net R <= 0)"

    return {
        "folds": len(folds),
        "tuned_pooled_avg_r": tuned_r,
        "tuned_valid_trades": tuned_trades,
        "baseline_pooled_avg_r": baseline_r,
        "baseline_valid_trades": baseline_trades,
        "verdict": verdict,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .data import DataClient

    config = AppConfig.from_env()
    client = DataClient(config)
    market_histories = {
        symbol: client.fetch_market_daily(symbol) for symbol in config.market_symbols
    }
    for symbol in config.symbols:
        daily = client.fetch_market_daily(symbol)
        if daily is None or len(daily) < 220:
            print(f"{symbol}: not enough daily history for walk-forward; skipped.")
            continue
        # 1y of free data (~250 bars) fits smaller windows than the defaults.
        collected: list = []
        folds = walk_forward(
            symbol, daily, config, market_histories, train_bars=150, valid_bars=50,
            trade_sink=collected,
        )
        print(f"=== {symbol} ===")
        for fold in folds:
            print(
                f"fold {fold.fold}: train[{fold.train_start}:{fold.train_end}] "
                f"best={fold.best_params} train_r={fold.train_avg_r} "
                f"valid_r={fold.valid_avg_r} (n={fold.valid_trades}) "
                f"baseline_r={fold.baseline_valid_avg_r} (n={fold.baseline_valid_trades})"
            )
        report = summarize(folds)
        print(
            f"summary: folds={report['folds']} "
            f"tuned_r={report['tuned_pooled_avg_r']} (n={report['tuned_valid_trades']}) "
            f"baseline_r={report['baseline_pooled_avg_r']} (n={report['baseline_valid_trades']})"
        )
        print(f"verdict: {report['verdict']}")
        if collected:
            from .attribution import attribution_report, format_report

            print("--- attribution (tuned validation trades) ---")
            print(format_report(attribution_report(collected, market_histories.get("SPY"))))
    return 0


def _grid_combos(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = sorted(grid)
    return [dict(zip(keys, values)) for values in product(*(grid[key] for key in keys))]


def _with_strategy(
    config: AppConfig,
    params: dict[str, Any],
    strategy: StrategyConfig | None = None,
) -> AppConfig:
    base = strategy if strategy is not None else config.strategy
    return replace(config, strategy=replace(base, **params))


def _pooled_r(pairs: list[tuple[float, int]]) -> Optional[float]:
    total_trades = sum(trades for _r, trades in pairs)
    if total_trades <= 0:
        return None
    return round(sum(r * trades for r, trades in pairs) / total_trades, 3)


if __name__ == "__main__":
    raise SystemExit(main())
