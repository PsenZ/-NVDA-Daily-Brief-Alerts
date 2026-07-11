from datetime import datetime

from veyraquant.memory import sync_decision_log
from veyraquant.models import SignalResult, TradePlan
from veyraquant.timeutils import SYDNEY_TZ


def _make_result(symbol: str, signal_hash: str, *, action: str = "BUY_TRIGGER") -> SignalResult:
    actionable = action in {"BUY_TRIGGER", "ADD_TRIGGER"}
    plan = TradePlan(
        entry_zone="$100.00 - $101.00" if actionable else "NA",
        stop="$98.00" if actionable else "NA",
        targets="$104.00 / $106.00" if actionable else "NA",
        position_pct=6.0 if actionable else 0.0,
        max_loss_pct=0.5 if actionable else 0.0,
        rr=1.8 if actionable else 0.0,
        trigger="trigger",
        cancel="cancel",
    )
    return SignalResult(
        rank=1,
        symbol=symbol,
        signal_type=action,
        score=85,
        market_regime="风险偏好",
        entry_zone=plan.entry_zone,
        stop=plan.stop,
        targets=plan.targets,
        position_pct=plan.position_pct,
        max_loss_pct=plan.max_loss_pct,
        reasons=["trend is aligned"],
        risks=["watch for failed follow-through"],
        contributions={"trend": 12.0},
        trade_plan=plan,
        alert_kind="breakout_entry",
        signal_hash=signal_hash,
        last_price=100.0,
        action=action,
        is_actionable=actionable,
        plan_kind="buy" if action == "BUY_TRIGGER" else "add" if action == "ADD_TRIGGER" else "wait",
        rating="Buy" if action == "BUY_TRIGGER" else "Overweight",
        bull_case=["trend, momentum, and volume align"],
        bear_case=["failed breakout would negate the setup"],
        market_evidence=["QQQ and SMH both support the tape."],
        portfolio_decision="approved",
        portfolio_reason="Approved as a top-ranked idea.",
    )


def test_sync_decision_log_appends_unique_entries(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    now_dt = datetime(2026, 5, 3, 7, 30, tzinfo=SYDNEY_TZ)
    results = [
        _make_result("NVDA", "hash-1"),
        _make_result("AMD", "hash-2", action="ADD_TRIGGER"),
    ]

    entries = sync_decision_log(str(path), now_dt, results, holding_days=5, fetch_return=lambda *_: None)
    second_pass = sync_decision_log(str(path), now_dt, results, holding_days=5, fetch_return=lambda *_: None)

    assert len(entries) == 2
    assert len(second_pass) == 2
    assert {entry["symbol"] for entry in second_pass} == {"NVDA", "AMD"}
    assert all(entry["outcome_status"] == "pending" for entry in second_pass)


def test_sync_decision_log_resolves_pending_outcomes(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    initial_dt = datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    later_dt = datetime(2026, 4, 28, 7, 30, tzinfo=SYDNEY_TZ)
    result = _make_result("NVDA", "hash-1")

    sync_decision_log(str(path), initial_dt, [result], holding_days=5, fetch_return=lambda *_: None)

    def fake_return(symbol: str, _trade_date: str, _holding_days: int) -> float | None:
        if symbol == "NVDA":
            return 0.08
        if symbol == "SPY":
            return 0.03
        return None

    entries = sync_decision_log(str(path), later_dt, [], holding_days=5, fetch_return=fake_return)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["outcome_status"] == "resolved"
    assert entry["five_day_return"] == 0.08
    assert entry["alpha_vs_spy"] == 0.05


def test_sync_decision_log_marks_unresolved_when_returns_missing(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    initial_dt = datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    later_dt = datetime(2026, 4, 28, 7, 30, tzinfo=SYDNEY_TZ)
    result = _make_result("SMH", "hash-3")

    sync_decision_log(str(path), initial_dt, [result], holding_days=5, fetch_return=lambda *_: None)
    entries = sync_decision_log(str(path), later_dt, [], holding_days=5, fetch_return=lambda *_: None)

    assert len(entries) == 1
    assert entries[0]["outcome_status"] == "unresolved"
    assert entries[0]["five_day_return"] is None
    assert entries[0]["alpha_vs_spy"] is None


def test_multi_horizon_returns_filled_on_resolution(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    initial_dt = datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    later_dt = datetime(2026, 4, 28, 7, 30, tzinfo=SYDNEY_TZ)
    sync_decision_log(str(path), initial_dt, [_make_result("NVDA", "h1")], holding_days=5, fetch_return=lambda *_: None)

    def fake_return(symbol, _date, days):
        return days * (0.01 if symbol == "NVDA" else 0.004)

    entries = sync_decision_log(str(path), later_dt, [], holding_days=5, fetch_return=fake_return)
    entry = entries[0]

    assert entry["outcome_status"] == "resolved"
    assert entry["horizon_returns"] == {"1": 0.01, "3": 0.03, "5": 0.05, "10": 0.1}
    assert entry["horizon_alphas"]["5"] == 0.03
    assert entry["horizon_alphas"]["10"] == 0.06
    # Primary fields stay aligned with the 5-day horizon.
    assert entry["five_day_return"] == 0.05
    assert entry["alpha_vs_spy"] == 0.03


def test_missing_long_horizon_backfilled_on_later_run(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    initial_dt = datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    resolve_dt = datetime(2026, 4, 28, 7, 30, tzinfo=SYDNEY_TZ)
    backfill_dt = datetime(2026, 5, 6, 7, 30, tzinfo=SYDNEY_TZ)
    sync_decision_log(str(path), initial_dt, [_make_result("NVDA", "h1")], holding_days=5, fetch_return=lambda *_: None)

    def early_fetch(symbol, _date, days):
        if days >= 10:
            return None  # 10-day horizon not observable yet
        return days * (0.01 if symbol == "NVDA" else 0.004)

    entries = sync_decision_log(str(path), resolve_dt, [], holding_days=5, fetch_return=early_fetch)
    assert entries[0]["outcome_status"] == "resolved"
    assert "10" not in entries[0]["horizon_returns"]

    def late_fetch(symbol, _date, days):
        return days * (0.01 if symbol == "NVDA" else 0.004)

    entries = sync_decision_log(str(path), backfill_dt, [], holding_days=5, fetch_return=late_fetch)
    entry = entries[0]
    assert entry["outcome_status"] == "resolved"
    assert entry["horizon_returns"]["10"] == 0.1
    assert entry["horizon_alphas"]["10"] == 0.06
    # Already-filled horizons are not refetched/overwritten.
    assert entry["horizon_returns"]["5"] == 0.05
