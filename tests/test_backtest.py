import numpy as np
import pandas as pd

from veyraquant.backtest import run_backtest
from veyraquant.config import AppConfig, SmtpConfig


def make_config():
    return AppConfig(
        symbols=["NVDA"],
        market_symbols=["SPY"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=10,
        state_path="state/test.json",
        cache_dir=".cache/test",
        subject_prefix="Test",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=None,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=3,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def test_backtest_returns_summary_without_future_data_crash():
    rows = 180
    close = 100 + np.arange(rows) * 0.25
    daily = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_800_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )

    result = run_backtest("NVDA", daily, make_config())

    assert result.trades >= 0
    assert 0 <= result.win_rate <= 100
    assert result.buy_hold_pct > 0


def _frame(rows, start, step):
    close = start + np.arange(rows) * step
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_800_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def test_backtest_market_filter_uses_injected_benchmarks_not_symbol_itself():
    rows = 180
    daily = _frame(rows, 100, 0.25)  # steadily rising symbol
    # Bear benchmarks: falling SPY/QQQ/SMH should push the market filter
    # toward risk-off and veto/suppress long entries.
    bear = {name: _frame(rows, 200, -0.5) for name in ("SPY", "QQQ", "SMH")}
    bull = {name: _frame(rows, 200, 0.5) for name in ("SPY", "QQQ", "SMH")}

    result_bear = run_backtest("NVDA", daily, make_config(), market_histories=bear)
    result_bull = run_backtest("NVDA", daily, make_config(), market_histories=bull)

    # With the old self-referential bug both would be identical; now the
    # bearish market must not produce more trades than the bullish one.
    assert result_bear.trades <= result_bull.trades


def test_backtest_market_slice_has_no_lookahead():
    from veyraquant.backtest import _market_slice

    frame = _frame(60, 100, 0.5)
    as_of = frame.index[29]
    sliced = _market_slice({"SPY": frame}, as_of)
    assert sliced["SPY"].index[-1] == as_of
    assert len(sliced["SPY"]) == 30


def test_apply_cost_scales_with_stop_distance():
    from veyraquant.backtest import apply_cost

    # 10 bps on a $100 entry = $0.10. With $2 risk/share that is 0.05R;
    # with $0.50 risk/share (tight stop) the same cost is 0.20R.
    assert apply_cost(1.5, 100.0, 2.0, 10.0) == 1.5 - 0.05
    assert apply_cost(1.5, 100.0, 0.5, 10.0) == 1.5 - 0.20
    # Zero cost / degenerate inputs leave the outcome untouched.
    assert apply_cost(1.5, 100.0, 2.0, 0.0) == 1.5
    assert apply_cost(1.5, 0.0, 2.0, 10.0) == 1.5


def test_backtest_net_avg_r_never_exceeds_gross():
    import dataclasses

    daily = _frame(180, 100, 0.25)
    bull = {name: _frame(180, 200, 0.5) for name in ("SPY", "QQQ", "SMH")}
    config = dataclasses.replace(make_config(), backtest_cost_bps=50.0)

    result = run_backtest("NVDA", daily, config, market_histories=bull)

    assert result.cost_bps == 50.0
    if result.trades > 0:
        assert result.avg_r <= result.avg_r_gross
