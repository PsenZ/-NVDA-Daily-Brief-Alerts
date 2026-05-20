from veyraquant.decision_manager import apply_portfolio_manager
from veyraquant.models import MarketContext, SignalResult, TradePlan


def make_result(symbol, action, score, conviction, *, sector_reason, validation_warnings=None):
    plan = TradePlan(
        entry_zone="$100.00 - $101.00" if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else "NA",
        stop="$98.00" if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else "NA",
        targets="$104.00 / $106.00" if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else "NA",
        position_pct=6.0 if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else 0.0,
        max_loss_pct=0.5 if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else 0.0,
        rr=1.8 if action in {"BUY_TRIGGER", "ADD_TRIGGER"} else 0.0,
        trigger="trigger",
        cancel="cancel",
    )
    return SignalResult(
        rank=1,
        symbol=symbol,
        signal_type=action,
        score=score,
        market_regime="风险偏好",
        entry_zone=plan.entry_zone,
        stop=plan.stop,
        targets=plan.targets,
        position_pct=plan.position_pct,
        max_loss_pct=plan.max_loss_pct,
        reasons=[sector_reason],
        risks=[],
        contributions={"trend": 10.0},
        trade_plan=plan,
        alert_kind="breakout_entry" if action == "BUY_TRIGGER" else "pullback_add",
        signal_hash=f"{symbol}-{action}",
        last_price=100.0,
        action=action,
        is_actionable=action in {"BUY_TRIGGER", "ADD_TRIGGER"},
        plan_kind="buy" if action == "BUY_TRIGGER" else "add" if action == "ADD_TRIGGER" else "wait",
        rating="Buy" if action == "BUY_TRIGGER" else "Overweight" if action == "ADD_TRIGGER" else "Hold",
        bull_case=["bull"],
        bear_case=["bear"],
        market_evidence=["QQQ holds trend."],
        conviction_level=conviction,
        validation_warnings=validation_warnings or [],
    )


def test_portfolio_manager_limits_same_sector_candidates():
    market = MarketContext("风险偏好", 18.0, ["QQQ strong"], [], {})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", sector_reason="semiconductor leader"),
        make_result("AMD", "ADD_TRIGGER", 82, "medium", sector_reason="semiconductor follow-through"),
        make_result("MU", "BUY_TRIGGER", 79, "medium", sector_reason="semiconductor catch-up"),
    ]

    reviewed, notes = apply_portfolio_manager(results, market)

    approved = [item for item in reviewed if item.portfolio_decision == "approved"]
    deferred = [item for item in reviewed if item.portfolio_decision == "deferred"]
    assert len(approved) == 2
    assert len(deferred) == 1
    assert any("concentration" in note for note in notes)


def test_portfolio_manager_reduces_approved_count_in_risk_off():
    market = MarketContext("风险规避", -8.0, ["risk off"], ["VIX elevated"], {})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", sector_reason="semiconductor leader"),
        make_result("AAPL", "BUY_TRIGGER", 84, "medium", sector_reason="mega-cap momentum"),
    ]

    reviewed, notes = apply_portfolio_manager(results, market)

    approved = [item for item in reviewed if item.portfolio_decision == "approved"]
    deferred = [item for item in reviewed if item.portfolio_decision == "deferred"]
    assert len(approved) == 1
    assert len(deferred) == 1
    assert any("Risk-off" in note for note in notes)


def test_portfolio_manager_prefers_cleaner_validation_when_ranks_are_close():
    market = MarketContext("风险偏好", 18.0, ["QQQ strong"], [], {})
    strong_but_warned = make_result(
        "NVDA",
        "BUY_TRIGGER",
        88,
        "high",
        sector_reason="semiconductor leader",
        validation_warnings=["entry zone width warning"],
    )
    clean_candidate = make_result(
        "AMD",
        "BUY_TRIGGER",
        87,
        "high",
        sector_reason="semiconductor follow-through",
    )

    reviewed, _notes = apply_portfolio_manager([strong_but_warned, clean_candidate], market)

    approved_symbols = [item.symbol for item in reviewed if item.portfolio_decision == "approved"]
    assert "AMD" in approved_symbols
