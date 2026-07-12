import pandas as pd

from veyraquant.attribution import (
    attach_benchmark_alpha,
    attribution_report,
    failure_taxonomy,
    format_report,
    group_metrics,
)
from veyraquant.evaluation import SimTrade


def trade(**overrides):
    base = dict(
        symbol="NVDA", entry_date=pd.Timestamp("2026-01-06"),
        entry_price=100.0, stop_price=95.0, target_price=110.0,
        shares=200.0, risk_pct=1.0, exit_date=pd.Timestamp("2026-01-08"),
        exit_price=110.0, exit_reason="target_hit", bars_held=2,
        r_gross=2.0, r_net=2.0, pnl=2000.0,
        setup_type="breakout_entry", market_regime="risk-on",
        sector="semiconductor", data_quality="HIGH",
    )
    base.update(overrides)
    return SimTrade(**base)


def test_failure_taxonomy_splits_timeout_by_outcome():
    trades = [
        trade(exit_reason="target_hit"),
        trade(exit_reason="gap_stop", r_net=-2.0),
        trade(exit_reason="timeout_exit", r_net=0.8),
        trade(exit_reason="timeout_exit", r_net=-0.5),
        trade(exit_reason="timeout_exit", r_net=0.01),
    ]
    taxonomy = failure_taxonomy(trades)
    assert taxonomy == {
        "target_hit": 1, "gap_stop": 1,
        "timeout_win": 1, "timeout_loss": 1, "timeout_flat": 1,
    }


def test_group_metrics_enforce_sample_guards():
    # 5 winning breakout trades: positive stats but NEVER significant and
    # always flagged insufficient below 30 samples.
    trades = [trade(r_net=1.0 + i * 0.1) for i in range(5)]
    row = group_metrics(trades, "setup_type")[0]
    assert row.key == "breakout_entry" and row.n == 5
    assert row.win_rate == 100.0
    assert row.significant is False        # n < 10 gate
    assert row.insufficient_sample is True # n < 30 no-strong-conclusions bar

    # 35 trades with a real edge: significance allowed, guard cleared.
    big = [trade(r_net=0.5 + (i % 3) * 0.1) for i in range(35)]
    row = group_metrics(big, "setup_type")[0]
    assert row.insufficient_sample is False
    assert row.significant is True


def test_benchmark_alpha_uses_the_trades_own_window_or_none():
    bench = pd.DataFrame(
        {"Close": [500.0, 505.0, 510.0]},
        index=pd.date_range("2026-01-06", periods=3, freq="B"),
    )
    matched = trade()          # entry 01-06 exit 01-08: both in benchmark
    unmatched = trade(exit_date=pd.Timestamp("2026-02-01"))  # exit missing
    open_trade = trade(exit_date=None)

    attach_benchmark_alpha([matched, unmatched, open_trade], bench)

    assert matched.benchmark_return == round(510.0 / 500.0 - 1, 6)
    assert matched.alpha == round(0.10 - matched.benchmark_return, 6)
    assert unmatched.alpha is None         # never approximated
    assert open_trade.alpha is None


def test_attribution_report_produces_all_cuts():
    trades = [
        trade(),
        trade(setup_type="pullback_add", market_regime="neutral", sector="mega_growth",
              data_quality="MEDIUM", exit_reason="stopped_out", r_net=-1.0),
    ]
    report = attribution_report(trades)
    assert report["trades"] == 2
    assert {row.key for row in report["by_setup"]} == {"breakout_entry", "pullback_add"}
    assert {row.key for row in report["by_regime"]} == {"risk-on", "neutral"}
    assert {row.key for row in report["by_sector"]} == {"semiconductor", "mega_growth"}
    assert {row.key for row in report["by_data_quality"]} == {"HIGH", "MEDIUM"}
    combos = {row.key for row in report["by_setup_regime"]}
    assert "breakout_entry in risk-on" in combos
    assert "pullback_add in neutral" in combos
    text = format_report(report)
    assert "insufficient sample" in text   # both groups are tiny


def test_benchmark_window_is_execution_consistent():
    """Entry leg = benchmark OPEN of entry day; gap exits measure the
    benchmark at its open, close-style exits at its close (R5.5)."""
    bench = pd.DataFrame(
        {
            "Open": [498.0, 503.0, 507.0],
            "Close": [500.0, 505.0, 510.0],
        },
        index=pd.date_range("2026-01-06", periods=3, freq="B"),
    )
    normal = trade(exit_reason="target_hit")           # exit day close 510
    gap = trade(exit_reason="gap_stop", exit_price=90.0, r_net=-2.0)  # exit day open 507

    attach_benchmark_alpha([normal, gap], bench)

    assert normal.benchmark_return == round(510.0 / 498.0 - 1, 6)  # open -> close
    assert gap.benchmark_return == round(507.0 / 498.0 - 1, 6)     # open -> open
    assert normal.alpha == round((110.0 / 100.0 - 1) - normal.benchmark_return, 6)
