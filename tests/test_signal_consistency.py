from datetime import datetime

import numpy as np
import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.models import FundamentalsData, MarketContext, NewsBundle, SignalResult, TechSnapshot, TradePlan
from veyraquant.reporting import compose_alert_email, compose_daily_report
from veyraquant.signals import analyze_symbol, enforce_portfolio_heat
from veyraquant.timeutils import SYDNEY_TZ


def make_config():
    return AppConfig(
        symbols=["NVDA"],
        market_symbols=["SPY", "QQQ", "SMH", "^VIX"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=30,
        state_path="state/test.json",
        cache_dir=".cache/test",
        subject_prefix="Test",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=100_000,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=3,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def dummy_daily(rows=100):
    close = 100 + np.arange(rows) * 0.5
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=pd.date_range("2026-01-01", periods=rows, freq="B"),
    )


def bullish_market():
    return MarketContext(
        label="风险偏好",
        score=20.0,
        reasons=["QQQ trend remains constructive."],
        risks=[],
        snapshots={"QQQ": {"perf20": 5.0}, "SMH": {"perf20": 6.0}, "SPY": {"perf20": 4.0}},
    )


def breakout_snapshot():
    return TechSnapshot(
        {
            "last": 104.0,
            "high_20": 104.1,
            "sma5": 100.0,
            "sma10": 99.0,
            "sma20": 98.0,
            "sma50": 96.0,
            "atr14": 2.0,
            "rsi14": 58.0,
            "vol_ratio_5": 2.2,
            "close_position": 0.82,
            "dist_ma5_pct": 4.0,
            "dist_ma10_pct": 5.0,
        }
    )


def pullback_snapshot():
    return TechSnapshot(
        {
            "last": 101.0,
            "high_20": 106.0,
            "sma5": 101.5,
            "sma10": 101.0,
            "sma20": 100.5,
            "sma50": 98.0,
            "atr14": 2.0,
            "rsi14": 54.0,
            "vol_ratio_5": 0.6,
            "close_position": 0.55,
            "dist_ma5_pct": -0.49,
            "dist_ma10_pct": 0.0,
        }
    )


def watch_snapshot():
    return TechSnapshot(
        {
            "last": 103.0,
            "high_20": 110.0,
            "sma5": 102.0,
            "sma10": 101.0,
            "sma20": 100.0,
            "sma50": 98.0,
            "atr14": 2.0,
            "rsi14": 57.0,
            "vol_ratio_5": 1.0,
            "close_position": 0.55,
            "dist_ma5_pct": 0.98,
            "dist_ma10_pct": 1.98,
        }
    )


def news_bundle(score):
    label = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
    return NewsBundle([], [], {"score": score, "label": label, "sample_size": 3})


def score_result(total_score):
    return {"base": float(total_score)}, ["scored"], []


def assert_result_consistency(result):
    if result.action in {"BUY_TRIGGER", "ADD_TRIGGER"}:
        assert result.is_actionable
        assert result.plan_kind in {"buy", "add"}
        assert result.position_pct > 0
        assert result.max_loss_pct > 0
        assert result.stop != "NA"
        assert result.targets != "NA"
    else:
        assert not result.is_actionable
        assert result.plan_kind in {"watch", "reduce", "wait", "reject"}
        assert result.position_pct == 0.0
        assert result.max_loss_pct == 0.0
        assert result.stop == "NA"
        assert result.targets == "NA"
    assert result.rating in {"Buy", "Overweight", "Hold", "Underweight", "No Trade"}
    assert result.conviction_level in {"high", "medium", "low"}
    assert result.decision_balance in {"favorable", "mixed", "fragile", "blocked", "defensive"}
    assert result.market_evidence
    assert result.bear_case is not None


def test_negative_news_veto_keeps_final_action_and_plan_consistent(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(-0.35),
        bullish_market(),
        make_config(),
    )

    assert result.setup_type == "breakout_entry"
    assert result.action == "REJECT"
    assert "negative_news_veto" in result.suppressed_by
    assert result.plan_kind == "reject"
    assert_result_consistency(result)


def test_rr_downgrade_removes_buy_plan_fields(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))
    monkeypatch.setattr(
        "veyraquant.signals.preview_trade_plan",
        lambda action, tech, config: TradePlan(
            entry_zone="$100.00 - $101.00",
            stop="$98.00",
            targets="$101.00 / $102.00",
            position_pct=5.0,
            max_loss_pct=0.5,
            rr=1.0,
            trigger="preview",
            cancel="preview",
            account_equity=config.account_equity,
            position_value=5_000.0,
        ),
    )

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.3),
        bullish_market(),
        make_config(),
    )

    assert result.action == "WATCH"
    assert "rr_below_min" in result.suppressed_by
    assert_result_consistency(result)


def test_watch_and_wait_outputs_are_non_actionable(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: watch_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(58))
    watch_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )

    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(45))
    wait_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )

    assert watch_result.action == "WATCH"
    assert wait_result.action == "WAIT"
    assert_result_consistency(watch_result)
    assert_result_consistency(wait_result)


def test_buy_and_add_triggers_keep_full_trade_plans(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))
    buy_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.3),
        bullish_market(),
        make_config(),
    )

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: pullback_snapshot())
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(64))
    add_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.2),
        bullish_market(),
        make_config(),
    )

    assert buy_result.action == "BUY_TRIGGER"
    assert add_result.action == "ADD_TRIGGER"
    assert_result_consistency(buy_result)
    assert_result_consistency(add_result)


def test_signal_result_new_fields_have_safe_defaults():
    plan = TradePlan(
        entry_zone="NA",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        rr=0.0,
        trigger="none",
        cancel="none",
    )

    result = SignalResult(
        rank=1,
        symbol="NVDA",
        signal_type="禁止交易/等待",
        score=0,
        market_regime="neutral",
        entry_zone="NA",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        reasons=[],
        risks=[],
        contributions={},
        trade_plan=plan,
        alert_kind="wait",
        signal_hash="abc123",
        last_price=None,
    )

    assert result.setup_type == ""
    assert result.action == "WAIT"
    assert result.is_actionable is False
    assert result.suppressed_by == []
    assert result.plan_kind == "wait"
    assert result.rating == "Hold"
    assert result.portfolio_decision == "watchlist"


def test_non_actionable_signal_does_not_consume_portfolio_heat():
    watch_plan = TradePlan(
        entry_zone="Observation only.",
        stop="NA",
        targets="NA",
        position_pct=8.0,
        max_loss_pct=0.8,
        rr=0.0,
        trigger="watch",
        cancel="watch",
    )
    buy_plan = TradePlan(
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=10.0,
        max_loss_pct=0.5,
        rr=2.0,
        trigger="buy",
        cancel="buy",
    )

    watch_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )
    watch_result.action = "WATCH"
    watch_result.is_actionable = False
    watch_result.plan_kind = "watch"
    watch_result.position_pct = 8.0
    watch_result.max_loss_pct = 0.8
    watch_result.trade_plan = watch_plan
    watch_result.entry_zone = watch_plan.entry_zone
    watch_result.stop = watch_plan.stop
    watch_result.targets = watch_plan.targets

    buy_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.3),
        bullish_market(),
        make_config(),
    )
    buy_result.action = "BUY_TRIGGER"
    buy_result.is_actionable = True
    buy_result.plan_kind = "buy"
    buy_result.position_pct = 10.0
    buy_result.max_loss_pct = 0.5
    buy_result.trade_plan = buy_plan
    buy_result.entry_zone = buy_plan.entry_zone
    buy_result.stop = buy_plan.stop
    buy_result.targets = buy_plan.targets

    results = enforce_portfolio_heat([watch_result, buy_result], 0.3)

    assert results[0].position_pct == 8.0
    assert results[0].max_loss_pct == 0.8
    assert results[1].position_pct == 6.0
    assert results[1].max_loss_pct == 0.3
    assert results[1].portfolio_warnings


def test_reporting_can_render_non_actionable_signals_without_crashing():
    plan = TradePlan(
        entry_zone="Observation only.",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        rr=0.0,
        trigger="Wait for a cleaner entry.",
        cancel="None.",
    )
    watch_result = SignalResult(
        rank=1,
        symbol="NVDA",
        signal_type="持有观察",
        score=58,
        market_regime="风险偏好",
        entry_zone="Observation only.",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        reasons=["trend remains intact"],
        risks=["entry is not clean enough"],
        contributions={"trend": 10.0},
        trade_plan=plan,
        alert_kind="wait",
        signal_hash="watch-1",
        last_price=100.0,
        action="WATCH",
        plan_kind="watch",
        rating="Hold",
        bull_case=["trend remains intact"],
        bear_case=["entry is not clean enough"],
        market_evidence=["QQQ trend remains constructive."],
        portfolio_decision="watchlist",
        portfolio_reason="Not ready for execution today.",
    )
    reject_result = SignalResult(
        rank=2,
        symbol="QQQ",
        signal_type="禁止交易/等待",
        score=72,
        market_regime="风险偏好",
        entry_zone="Rejected.",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        reasons=["setup looked interesting"],
        risks=["plan validation failed"],
        contributions={"trend": 10.0},
        trade_plan=plan,
        alert_kind="wait",
        signal_hash="reject-1",
        last_price=100.0,
        action="REJECT",
        plan_kind="reject",
        rating="No Trade",
        bull_case=["setup looked interesting"],
        bear_case=["plan validation failed"],
        market_evidence=["Market regime is risk-on."],
        rejection_reasons=["target1 must exceed entry_high"],
        suppressed_by=["trade_plan_validation_failed"],
        portfolio_decision="rejected",
        portfolio_reason="Blocked before portfolio approval.",
    )

    subject, daily_body = compose_daily_report(
        [watch_result, reject_result],
        bullish_market(),
        make_config(),
        datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ),
        [],
    )
    alert_subject, alert_body = compose_alert_email(
        watch_result, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    assert subject
    assert "[Watchlist]" in daily_body
    assert "[Rejected Plans]" in daily_body
    assert "NVDA | Hold | 58" in daily_body
    assert "QQQ | score 72" in daily_body
    assert "Trade Alert" in alert_body
    assert "why now:" in alert_body
    assert "watch risk:" in alert_body
    assert "Hold / WATCH" in alert_subject
