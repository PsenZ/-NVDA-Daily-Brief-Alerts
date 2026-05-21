from types import SimpleNamespace

from veyraquant.config import (
    DEFAULT_SECTOR_MAP,
    DEFAULT_SECTOR_POSITION_LIMITS,
    DEFAULT_SECTOR_RISK_LIMITS,
)
from veyraquant.decision_manager import apply_portfolio_manager
from veyraquant.models import MarketContext, SignalResult, TradePlan


def make_config(**overrides):
    values = {
        "sector_map": dict(DEFAULT_SECTOR_MAP),
        "sector_risk_limits": dict(DEFAULT_SECTOR_RISK_LIMITS),
        "sector_position_limits": dict(DEFAULT_SECTOR_POSITION_LIMITS),
        "max_approved_actions_risk_on": 3,
        "max_approved_actions_neutral": 2,
        "max_approved_actions_risk_off": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_result(
    symbol,
    action,
    score,
    conviction,
    *,
    position_pct=6.0,
    max_loss_pct=0.5,
    validation_warnings=None,
    raw_score=None,
):
    actionable = action in {"BUY_TRIGGER", "ADD_TRIGGER"}
    plan = TradePlan(
        entry_zone="$100.00 - $101.00" if actionable else "NA",
        stop="$98.00" if actionable else "NA",
        targets="$104.00 / $106.00" if actionable else "NA",
        position_pct=position_pct if actionable else 0.0,
        max_loss_pct=max_loss_pct if actionable else 0.0,
        rr=1.8 if actionable else 0.0,
        trigger="trigger",
        cancel="cancel",
    )
    return SignalResult(
        rank=1,
        symbol=symbol,
        signal_type=action,
        score=score,
        raw_score=float(score if raw_score is None else raw_score),
        market_regime="risk-on",
        entry_zone=plan.entry_zone,
        stop=plan.stop,
        targets=plan.targets,
        position_pct=plan.position_pct,
        max_loss_pct=plan.max_loss_pct,
        reasons=["portfolio test"],
        risks=[],
        contributions={"trend": 10.0},
        trade_plan=plan,
        alert_kind="breakout_entry" if action == "BUY_TRIGGER" else "pullback_add",
        signal_hash=f"{symbol}-{action}",
        last_price=100.0,
        action=action,
        is_actionable=actionable,
        plan_kind="buy" if action == "BUY_TRIGGER" else "add" if action == "ADD_TRIGGER" else "wait",
        rating="Buy" if action == "BUY_TRIGGER" else "Overweight" if action == "ADD_TRIGGER" else "Hold",
        bull_case=["bull"],
        bear_case=["bear"],
        market_evidence=["QQQ holds trend."],
        conviction_level=conviction,
        validation_warnings=validation_warnings or [],
    )


def test_sector_risk_budget_defers_lower_ranked_semiconductor_candidate():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.5),
        make_result("AMD", "ADD_TRIGGER", 82, "medium", max_loss_pct=0.5),
        make_result("MU", "BUY_TRIGGER", 79, "medium", max_loss_pct=0.5),
    ]

    reviewed, notes = apply_portfolio_manager(results, market, make_config())

    approved = [item for item in reviewed if item.portfolio_decision == "approved"]
    deferred = [item for item in reviewed if item.portfolio_decision == "deferred"]
    assert [item.symbol for item in approved] == ["NVDA", "AMD"]
    assert [item.symbol for item in deferred] == ["MU"]
    assert deferred[0].defer_reason_code == "sector_risk_limit_exceeded"
    assert any("risk budget" in note for note in notes)


def test_higher_approval_rank_score_gets_sector_budget_first():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    results = [
        make_result("MU", "BUY_TRIGGER", 78, "medium", max_loss_pct=0.7),
        make_result("NVDA", "BUY_TRIGGER", 93, "high", max_loss_pct=0.7),
        make_result("AMD", "ADD_TRIGGER", 80, "medium", max_loss_pct=0.2),
    ]

    reviewed, _notes = apply_portfolio_manager(results, market, make_config())

    approved_symbols = [item.symbol for item in reviewed if item.portfolio_decision == "approved"]
    deferred_symbols = [item.symbol for item in reviewed if item.portfolio_decision == "deferred"]
    assert "NVDA" in approved_symbols
    assert "AMD" in approved_symbols
    assert "MU" in deferred_symbols


def test_sector_position_limit_defers_candidate_when_position_budget_is_full():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(sector_risk_limits={"semiconductor": 3.0, "general": 1.0})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", position_pct=12.0, max_loss_pct=0.5),
        make_result("AMD", "ADD_TRIGGER", 82, "medium", position_pct=12.0, max_loss_pct=0.5),
    ]

    reviewed, notes = apply_portfolio_manager(results, market, config)

    approved = [item for item in reviewed if item.portfolio_decision == "approved"]
    deferred = [item for item in reviewed if item.portfolio_decision == "deferred"]
    assert [item.symbol for item in approved] == ["NVDA"]
    assert [item.symbol for item in deferred] == ["AMD"]
    assert deferred[0].defer_reason_code == "sector_position_limit_exceeded"
    assert any("position exposure" in note for note in notes)


def test_neutral_and_risk_off_approved_limits_are_stricter():
    neutral = MarketContext("neutral", 5.0, ["mixed"], [], {})
    risk_off = MarketContext("risk-off", -8.0, ["risk off"], ["VIX elevated"], {})
    neutral_results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.3),
        make_result("AAPL", "BUY_TRIGGER", 84, "medium", max_loss_pct=0.3),
        make_result("TSLA", "BUY_TRIGGER", 82, "medium", max_loss_pct=0.3),
    ]
    risk_off_results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.3),
        make_result("AAPL", "BUY_TRIGGER", 84, "medium", max_loss_pct=0.3),
    ]

    neutral_reviewed, neutral_notes = apply_portfolio_manager(neutral_results, neutral, make_config())
    risk_off_reviewed, risk_off_notes = apply_portfolio_manager(risk_off_results, risk_off, make_config())

    assert len([item for item in neutral_reviewed if item.portfolio_decision == "approved"]) == 2
    assert len([item for item in neutral_reviewed if item.portfolio_decision == "deferred"]) == 1
    assert len([item for item in risk_off_reviewed if item.portfolio_decision == "approved"]) == 0
    assert len([item for item in risk_off_reviewed if item.portfolio_decision == "deferred"]) == 2
    assert any("Neutral" in note for note in neutral_notes)
    assert any("Risk-off" in note for note in risk_off_notes)


def test_unconfigured_portfolio_manager_uses_default_sector_guard():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.5),
        make_result("AMD", "ADD_TRIGGER", 82, "medium", max_loss_pct=0.5),
        make_result("MU", "BUY_TRIGGER", 79, "medium", max_loss_pct=0.5),
    ]

    reviewed, _notes = apply_portfolio_manager(results, market)

    approved = [item.symbol for item in reviewed if item.portfolio_decision == "approved"]
    deferred = [item for item in reviewed if item.portfolio_decision == "deferred"]
    assert approved == ["NVDA", "AMD"]
    assert deferred[0].defer_reason_code == "sector_risk_limit_exceeded"


def test_non_actionable_never_enters_approved_set():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high"),
        make_result("TSLA", "RISK_REDUCE", 38, "medium"),
        make_result("QQQ", "REJECT", 72, "low"),
    ]

    reviewed, _notes = apply_portfolio_manager(results, market, make_config())

    decisions = {item.symbol: item.portfolio_decision for item in reviewed}
    assert decisions["NVDA"] == "approved"
    assert decisions["TSLA"] == "risk_action"
    assert decisions["QQQ"] == "rejected"
