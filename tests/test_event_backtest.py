"""R4 acceptance: event-driven execution semantics, worst case by default."""
from types import SimpleNamespace

import pandas as pd

from veyraquant.evaluation import TradeSignal, run_event_backtest


def make_config(**overrides):
    base = dict(
        backtest_cost_bps=0.0,       # zero cost -> exact R assertions
        portfolio_heat_max_pct=3.0,
        max_position_pct=100.0,      # neutralize the value cap unless tested
        account_equity=100_000.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def frame(rows, start="2026-01-05"):
    idx = pd.date_range(start, periods=len(rows), freq="B")
    return pd.DataFrame(
        [dict(zip(["Open", "High", "Low", "Close"], row), Volume=1e6) for row in rows],
        index=idx,
    )


BASE_ROWS = [
    (100, 101, 99, 100),   # 0: signal forms at this close
    (100, 101, 99, 100),   # 1: entry at next open = 100
    (102, 111, 101, 105),  # 2: high touches target 110
    (105, 106, 104, 105),
    (105, 106, 104, 105),
]


def sig(symbol="AAA", stop=95.0, target=110.0, risk=1.0, score=10.0):
    return TradeSignal(symbol, 0, stop, target, risk, score)


def test_next_open_execution_and_target_hit():
    result = run_event_backtest({"AAA": frame(BASE_ROWS)}, [sig()], make_config())
    trade = result.trades[0]
    assert trade.entry_price == 100.0            # next bar's open, not signal close
    assert trade.exit_reason == "target_hit"
    assert trade.exit_price == 110.0             # intrabar touch fills at target
    assert trade.r_net == 2.0                    # (110-100)/(100-95)
    assert result.final_equity - result.starting_equity == sum(t.pnl for t in result.trades)


def test_gap_through_stop_fills_at_open_not_stop():
    rows = list(BASE_ROWS)
    rows[2] = (90, 92, 88, 91)                   # opens far below the 95 stop
    result = run_event_backtest({"AAA": frame(rows)}, [sig()], make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "gap_stop"
    assert trade.exit_price == 90.0              # the open, worse than the stop
    assert trade.r_net == -2.0                   # loss exceeds -1R: gaps are real


def test_same_bar_stop_and_target_resolves_to_stop_first():
    rows = list(BASE_ROWS)
    rows[2] = (100, 115, 94, 108)                # touches 110 target AND 95 stop
    result = run_event_backtest({"AAA": frame(rows)}, [sig()], make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "stopped_out"    # never the favorable resolution
    assert trade.exit_price == 95.0
    assert trade.r_net == -1.0


def test_gap_beyond_target_fills_at_open():
    rows = list(BASE_ROWS)
    rows[2] = (115, 118, 114, 116)
    result = run_event_backtest({"AAA": frame(rows)}, [sig()], make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "gap_target"
    assert trade.r_net == 3.0                    # favorable gap: you get the open


def test_timeout_exit_at_close_after_holding_bars():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (101, 102, 100, 101),
        (102, 103, 101, 102),
    ]
    result = run_event_backtest(
        {"AAA": frame(rows)}, [sig(target=999.0)], make_config(), holding_bars=2
    )
    trade = result.trades[0]
    assert trade.exit_reason == "timeout_exit"
    assert trade.bars_held == 2
    assert trade.exit_price == 102.0


def test_missing_trading_day_does_not_break_holding_count():
    full = frame(BASE_ROWS)
    gapped = full.drop(full.index[2])            # AAA missing one session
    other = frame([(50, 51, 49, 50)] * 5)        # BBB supplies that timeline date
    result = run_event_backtest(
        {"AAA": gapped, "BBB": other},
        [sig(target=999.0)],
        make_config(),
        holding_bars=2,
    )
    trade = result.trades[0]
    assert trade.exit_reason == "timeout_exit"
    assert trade.bars_held == 2                  # bars, not calendar days
    assert trade.exit_date == gapped.index[-1]


def test_same_day_entries_share_heat_by_score_with_haircut_and_skip():
    frames = {name: frame(BASE_ROWS) for name in ("AAA", "BBB", "CCC")}
    signals = [
        sig("AAA", risk=1.0, score=90),
        sig("BBB", risk=1.0, score=50),
        sig("CCC", risk=1.0, score=10),
    ]
    config = make_config(portfolio_heat_max_pct=1.5)
    result = run_event_backtest(frames, signals, config)

    by_symbol = {t.symbol: t for t in result.trades}
    assert by_symbol["AAA"].risk_pct == 1.0      # top score gets full risk
    assert abs(by_symbol["BBB"].risk_pct - 0.5) < 1e-9  # haircut to remaining heat
    assert "CCC" not in by_symbol                # nothing left
    assert result.skipped_for_heat == 1


def test_entry_bar_stop_touch_exits_same_day_but_target_is_not_granted():
    rows = list(BASE_ROWS)
    rows[1] = (100, 112, 94, 108)  # entry bar later touches BOTH 95 stop and 110 target
    result = run_event_backtest({"AAA": frame(rows)}, [sig()], make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "stopped_out"
    assert trade.exit_date == trade.entry_date   # same-day worst-case exit
    assert trade.r_net == -1.0                   # never the favorable resolution


def test_entry_cancelled_when_open_already_broke_the_setup():
    rows = list(BASE_ROWS)
    rows[1] = (94, 96, 93, 95)                   # next open below the 95 stop
    result = run_event_backtest({"AAA": frame(rows)}, [sig()], make_config())
    assert result.trades == []
    assert result.cancelled_entries == 1


def test_split_adjusted_scale_invariance():
    """A 2:1 split (adjusted data halves all prices) must not change R."""
    base = run_event_backtest({"AAA": frame(BASE_ROWS)}, [sig()], make_config())
    halved_rows = [tuple(v / 2 for v in row) for row in BASE_ROWS]
    halved = run_event_backtest(
        {"AAA": frame(halved_rows)}, [sig(stop=47.5, target=55.0)], make_config()
    )
    assert halved.trades[0].r_net == base.trades[0].r_net
    assert abs(halved.total_return_pct - base.total_return_pct) < 1e-9


def test_costs_and_slippage_reduce_r_and_position_cap_scales_risk():
    costly = run_event_backtest(
        {"AAA": frame(BASE_ROWS)}, [sig()], make_config(backtest_cost_bps=50.0)
    )
    assert costly.trades[0].r_net < costly.trades[0].r_gross

    slipped = run_event_backtest(
        {"AAA": frame(BASE_ROWS)}, [sig()], make_config(), slippage_bps=100.0
    )
    assert slipped.trades[0].entry_price == 101.0  # adverse fill on entry

    capped = run_event_backtest(
        {"AAA": frame(BASE_ROWS)}, [sig(risk=1.0)], make_config(max_position_pct=10.0)
    )
    trade = capped.trades[0]
    # 1% risk with a $5 stop wants $20k of stock; the 10% cap allows $10k,
    # so shares and effective risk are halved together.
    assert abs(trade.risk_pct - 0.5) < 1e-9


def test_equity_curve_marks_open_positions_to_market():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # entry day, closes at 100
        (104, 105, 103, 104),  # open position worth +4/share before any exit
        (104, 106, 103, 105),
        (105, 106, 104, 105),
    ]
    result = run_event_backtest(
        {"AAA": frame(rows)}, [sig(target=999.0)], make_config(), holding_bars=10
    )
    curve = dict(result.equity_curve)
    day2 = curve[frame(rows).index[2]]
    # 1% risk, $5 stop -> 200 shares; +$4 unrealized = +$800 on 100k.
    assert abs(day2 - 100_800.0) < 1e-6
