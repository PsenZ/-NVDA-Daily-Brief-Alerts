from datetime import date

from veyraquant.armed_plans import (
    active_plans,
    add_trading_days,
    build_armed_plans,
    expire_stale_plans,
    load_plans,
    merge_plans,
    save_plans,
)

from test_signals_reporting import make_result


def approved_buy(symbol="NVDA"):
    result = make_result(
        symbol,
        "BUY_TRIGGER",
        "breakout",
        82,
        setup_type="breakout_entry",
        rating="Buy",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$100.00 - $101.00",
        stop="$96.00",
        targets="$107.50 / $112.00",
        position_pct=6.4,
        max_loss_pct=0.5,
        portfolio_decision="approved",
        portfolio_reason="Approved.",
    )
    result.trade_plan.entry_low = 100.0
    result.trade_plan.entry_high = 101.0
    result.trade_plan.stop_price = 96.0
    result.trade_plan.target1 = 107.5
    result.trade_plan.target2 = 112.0
    return result


def test_add_trading_days_skips_weekends():
    friday = date(2026, 7, 10)
    assert add_trading_days(friday, 2) == date(2026, 7, 14)  # Mon, Tue
    assert add_trading_days(friday, 0) == friday


def test_build_armed_plans_only_freezes_approved_actionable():
    approved = approved_buy()
    watch = make_result("AAPL", "WATCH", "hold", 58, portfolio_decision="watchlist")
    deferred = approved_buy("MSFT")
    deferred.portfolio_decision = "deferred"

    plans = build_armed_plans([approved, watch, deferred], date(2026, 7, 10), 2)

    assert [plan["symbol"] for plan in plans] == ["NVDA"]
    plan = plans[0]
    assert plan["status"] == "armed"
    assert plan["entry_low"] == 100.0
    assert plan["stop_price"] == 96.0
    assert plan["expires_date"] == "2026-07-14"


def test_merge_replaces_armed_plan_for_same_symbol_and_prunes_old_resolved():
    today = date(2026, 7, 10)
    old_armed = {"symbol": "NVDA", "status": "armed", "created_date": "2026-07-08"}
    recent_done = {"symbol": "AMD", "status": "triggered", "created_date": "2026-07-06"}
    stale_done = {"symbol": "MU", "status": "expired", "created_date": "2026-06-01"}
    fresh = build_armed_plans([approved_buy()], today, 2)

    merged = merge_plans([old_armed, recent_done, stale_done], fresh, today)

    symbols = [(plan["symbol"], plan["status"]) for plan in merged]
    assert ("NVDA", "armed") in symbols
    assert ("AMD", "triggered") in symbols
    assert all(symbol != "MU" for symbol, _status in symbols)
    assert len([s for s, status in symbols if s == "NVDA"]) == 1


def test_expire_marks_active_plans_past_expiry():
    plans = [
        {"symbol": "NVDA", "status": "armed", "expires_date": "2026-07-09"},
        {"symbol": "AMD", "status": "armed", "expires_date": "2026-07-14"},
    ]
    changed = expire_stale_plans(plans, date(2026, 7, 10))
    assert changed
    assert plans[0]["status"] == "expired"
    assert plans[1]["status"] == "armed"
    assert [plan["symbol"] for plan in active_plans(plans)] == ["AMD"]


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "armed.json")
    plans = build_armed_plans([approved_buy()], date(2026, 7, 10), 2)
    save_plans(path, plans)
    assert load_plans(path) == plans
    assert load_plans(str(tmp_path / "missing.json")) == []
