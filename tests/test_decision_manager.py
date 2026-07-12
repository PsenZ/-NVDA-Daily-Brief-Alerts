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


# --- R3.5: global heat is allocated only after approval checks ---

def test_deferred_candidate_does_not_consume_global_heat():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(portfolio_heat_max_pct=1.2)
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.7),
        make_result("AMD", "BUY_TRIGGER", 85, "medium", max_loss_pct=0.7),   # sector-deferred
        make_result("AAPL", "BUY_TRIGGER", 80, "medium", max_loss_pct=0.5),  # mega_growth
    ]

    reviewed, _notes = apply_portfolio_manager(results, market, config)

    decisions = {item.symbol: item for item in reviewed}
    assert decisions["AMD"].portfolio_decision == "deferred"
    assert decisions["AMD"].defer_reason_code == "sector_risk_limit_exceeded"
    # With the old pre-allocation bug, AMD would have eaten 0.7 heat and
    # AAPL would have been trimmed. Now AAPL gets its full 0.5.
    assert decisions["AAPL"].portfolio_decision == "approved"
    assert decisions["AAPL"].max_loss_pct == 0.5
    assert decisions["AAPL"].approval_reason_code == "approved_clean"


def test_low_priority_candidate_gets_proportional_haircut():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(portfolio_heat_max_pct=1.0)
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", position_pct=6.0, max_loss_pct=0.6),
        make_result("AAPL", "BUY_TRIGGER", 80, "medium", position_pct=6.0, max_loss_pct=0.6),
    ]
    results[1].trade_plan.account_equity = 100_000.0

    reviewed, notes = apply_portfolio_manager(results, market, config)

    nvda = next(item for item in reviewed if item.symbol == "NVDA")
    aapl = next(item for item in reviewed if item.symbol == "AAPL")
    assert nvda.max_loss_pct == 0.6                       # priority gets full risk
    assert aapl.portfolio_decision == "approved"
    assert aapl.approval_reason_code == "portfolio_heat_haircut"
    assert abs(aapl.max_loss_pct - 0.4) < 1e-9            # trimmed to remaining heat
    assert abs(aapl.position_pct - 4.0) < 1e-9            # proportional
    assert aapl.trade_plan.max_loss_pct == aapl.max_loss_pct
    assert aapl.trade_plan.position_value == 100_000.0 * aapl.position_pct / 100
    assert any("trimmed" in note for note in notes)


def test_heat_exhaustion_defers_without_consuming_budgets():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(portfolio_heat_max_pct=0.6)
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.6),
        make_result("AAPL", "BUY_TRIGGER", 80, "medium", max_loss_pct=0.5),
    ]

    reviewed, _notes = apply_portfolio_manager(results, market, config)

    aapl = next(item for item in reviewed if item.symbol == "AAPL")
    assert aapl.portfolio_decision == "deferred"
    assert aapl.defer_reason_code == "portfolio_heat_exhausted"
    # Untouched sizing: a heat-deferred candidate keeps its original plan.
    assert aapl.max_loss_pct == 0.5


def test_approved_heat_never_exceeds_cap_and_order_is_input_invariant():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(portfolio_heat_max_pct=1.5)

    def build():
        return [
            make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.7),
            make_result("AAPL", "BUY_TRIGGER", 84, "medium", max_loss_pct=0.7),
            make_result("TSLA", "BUY_TRIGGER", 78, "medium", max_loss_pct=0.7),
        ]

    forward, _n1 = apply_portfolio_manager(build(), market, config)
    shuffled_input = build()[::-1]
    backward, _n2 = apply_portfolio_manager(shuffled_input, market, config)

    def snapshot(reviewed):
        return {
            item.symbol: (item.portfolio_decision, item.max_loss_pct, item.approval_reason_code)
            for item in reviewed
        }

    assert snapshot(forward) == snapshot(backward)
    approved_heat = sum(
        item.max_loss_pct for item in forward if item.portfolio_decision == "approved"
    )
    assert approved_heat <= 1.5 + 1e-9


# --- R7 lite: correlation-aware sizing ---

def test_high_correlation_with_approved_name_halves_the_size():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(
        sector_risk_limits={"semiconductor": 3.0, "general": 3.0},
        portfolio_heat_max_pct=3.0, corr_threshold=0.85, corr_haircut_factor=0.5,
    )
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", position_pct=6.0, max_loss_pct=0.6),
        make_result("AMD", "BUY_TRIGGER", 82, "medium", position_pct=6.0, max_loss_pct=0.6),
    ]
    correlations = {frozenset(("NVDA", "AMD")): 0.93}

    reviewed, notes = apply_portfolio_manager(results, market, config, correlations=correlations)

    nvda = next(r for r in reviewed if r.symbol == "NVDA")
    amd = next(r for r in reviewed if r.symbol == "AMD")
    assert nvda.max_loss_pct == 0.6                       # first approval untouched
    assert amd.portfolio_decision == "approved"
    assert amd.approval_reason_code == "correlation_haircut"
    assert abs(amd.max_loss_pct - 0.3) < 1e-9             # halved
    assert abs(amd.position_pct - 3.0) < 1e-9
    assert amd.trade_plan.max_loss_pct == amd.max_loss_pct
    assert any("correlation" in note for note in notes)


def test_correlation_below_threshold_or_absent_changes_nothing():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(sector_risk_limits={"semiconductor": 3.0, "general": 3.0})
    def build():
        return [
            make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.6),
            make_result("AMD", "BUY_TRIGGER", 82, "medium", max_loss_pct=0.6),
        ]

    low_corr, _ = apply_portfolio_manager(
        build(), market, config, correlations={frozenset(("NVDA", "AMD")): 0.4}
    )
    none_corr, _ = apply_portfolio_manager(build(), market, config)

    for reviewed in (low_corr, none_corr):
        amd = next(r for r in reviewed if r.symbol == "AMD")
        assert amd.max_loss_pct == 0.6
        assert amd.approval_reason_code == "approved_clean"


def test_correlation_haircut_composes_with_heat_cap():
    market = MarketContext("risk-on", 18.0, ["QQQ strong"], [], {})
    config = make_config(
        sector_risk_limits={"semiconductor": 3.0, "general": 3.0},
        portfolio_heat_max_pct=0.8, corr_threshold=0.85, corr_haircut_factor=0.5,
    )
    results = [
        make_result("NVDA", "BUY_TRIGGER", 90, "high", max_loss_pct=0.6),
        make_result("AMD", "BUY_TRIGGER", 82, "medium", max_loss_pct=0.6),
    ]
    reviewed, _ = apply_portfolio_manager(
        results, market, config, correlations={frozenset(("NVDA", "AMD")): 0.95}
    )
    amd = next(r for r in reviewed if r.symbol == "AMD")
    # corr halves 0.6 -> 0.3; remaining heat is 0.2 -> heat haircut wins the label.
    assert amd.approval_reason_code == "portfolio_heat_haircut"
    assert amd.max_loss_pct <= 0.2 + 1e-9
    approved_heat = sum(r.max_loss_pct for r in reviewed if r.portfolio_decision == "approved")
    assert approved_heat <= 0.8 + 1e-9


def test_runner_correlation_helper_detects_comovement():
    import numpy as np
    import pandas as pd
    from types import SimpleNamespace as NS
    from veyraquant.runner import _candidate_correlations

    idx = pd.date_range("2026-01-01", periods=80, freq="B")
    rng = np.random.default_rng(5)
    base = rng.normal(0, 1, 80).cumsum() + 100
    twin = base * 1.001 + rng.normal(0, 0.05, 80)         # near-perfect co-mover
    unrelated = rng.normal(0, 1, 80).cumsum() + 100

    def item(sym, series):
        return NS(symbol=sym, daily=pd.DataFrame({"Close": series}, index=idx))

    results = [NS(symbol=s, is_actionable=True) for s in ("AAA", "BBB", "CCC")]
    correlations = _candidate_correlations(
        [item("AAA", base), item("BBB", twin), item("CCC", unrelated)],
        results, NS(corr_lookback_days=60),
    )
    assert correlations[frozenset(("AAA", "BBB"))] > 0.95
    assert abs(correlations[frozenset(("AAA", "CCC"))]) < 0.5
