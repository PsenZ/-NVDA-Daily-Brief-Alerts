from datetime import datetime

import numpy as np
import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.market import build_market_context
from veyraquant.models import FundamentalsData, MarketContext, NewsBundle, SignalResult, TechSnapshot, TradePlan
from veyraquant.reporting import compose_alert_email, compose_daily_report
from veyraquant.signals import analyze_symbol, choose_signal_type
from veyraquant.timeutils import SYDNEY_TZ


def make_config():
    return AppConfig(
        symbols=["NVDA", "MSFT"],
        market_symbols=["SPY", "QQQ", "SMH", "^VIX"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=10,
        state_path="state/test.json",
        cache_dir=".cache/test",
        subject_prefix="Test Brief",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=100_000,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=0.6,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def price_frame(rows=260, start=100, step=0.4):
    close = start + np.arange(rows) * step
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.5,
            "Low": close - 1.5,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def make_result(
    symbol,
    action,
    signal_type,
    score,
    *,
    setup_type="setup",
    rating="Hold",
    is_actionable=False,
    plan_kind="wait",
    entry_zone="NA",
    stop="NA",
    targets="NA",
    position_pct=0.0,
    max_loss_pct=0.0,
    reasons=None,
    risks=None,
    bull_case=None,
    bear_case=None,
    market_evidence=None,
    validation_warnings=None,
    warnings=None,
    rejection_reasons=None,
    suppressed_by=None,
    portfolio_decision="watchlist",
    portfolio_reason="Not ready yet.",
    raw_score=None,
):
    trade_plan = TradePlan(
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        position_pct=position_pct,
        max_loss_pct=max_loss_pct,
        rr=1.8 if is_actionable else 0.0,
        trigger="wait for trigger" if not is_actionable else "breakout confirmed",
        cancel="cancel if invalidated",
        account_equity=100_000 if is_actionable else None,
        position_value=8_000 if is_actionable else None,
    )
    return SignalResult(
        rank=1,
        symbol=symbol,
        signal_type=signal_type,
        score=score,
        raw_score=float(score if raw_score is None else raw_score),
        market_regime="风险偏好",
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        position_pct=position_pct,
        max_loss_pct=max_loss_pct,
        reasons=reasons or ["reason a", "reason b"],
        risks=risks or [],
        contributions={"trend": 10.0},
        trade_plan=trade_plan,
        alert_kind="breakout_entry" if action == "BUY_TRIGGER" else "wait",
        signal_hash=f"{symbol}-{action}",
        last_price=100.0,
        warnings=warnings or [],
        rejection_reasons=rejection_reasons or [],
        setup_type=setup_type,
        action=action,
        is_actionable=is_actionable,
        suppressed_by=suppressed_by or [],
        plan_kind=plan_kind,
        rating=rating,
        bull_case=bull_case or ["bull case"],
        bear_case=bear_case or ["bear case"],
        market_evidence=market_evidence or ["QQQ remains above SMA20."],
        conviction_level="high" if is_actionable else "low",
        decision_balance="mixed",
        validation_warnings=validation_warnings or [],
        portfolio_decision=portfolio_decision,
        portfolio_reason=portfolio_reason,
    )


def section(body: str, name: str) -> str:
    marker = f"[{name}]"
    start = body.index(marker)
    next_start = body.find("\n[", start + len(marker))
    if next_start == -1:
        return body[start:]
    return body[start:next_start]


def test_analyze_symbol_outputs_required_report_fields():
    config = make_config()
    daily = price_frame()
    market = build_market_context({"SPY": daily, "QQQ": daily, "SMH": daily})
    news = NewsBundle([], [], {"score": 0.3, "label": "bullish", "sample_size": 3})
    result = analyze_symbol(
        "NVDA",
        daily,
        None,
        FundamentalsData(recommendation_key="buy", revenue_growth=0.2),
        None,
        news,
        market,
        config,
    )

    assert result.symbol == "NVDA"
    assert result.score > 0
    assert result.entry_zone
    assert result.stop
    assert result.targets
    assert result.position_pct >= 0
    assert result.max_loss_pct >= 0
    assert result.bull_case
    assert result.bear_case
    assert result.market_evidence
    assert result.rating in {"Buy", "Overweight", "Hold", "Underweight", "No Trade"}
    assert result.conviction_level in {"high", "medium", "low"}


def test_daily_report_uses_briefing_structure():
    config = make_config()
    market = MarketContext(
        label="风险偏好",
        score=18.0,
        reasons=["QQQ above SMA20", "SMH strong"],
        risks=["VIX still elevated versus quiet tape."],
        snapshots={"SPY": {"last": 500, "sma20": 490, "sma50": 480, "perf20": 3.2}},
    )
    buy_result = make_result(
        "NVDA",
        "BUY_TRIGGER",
        "突破入场",
        100,
        rating="Buy",
        setup_type="breakout_entry",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=8.0,
        max_loss_pct=0.4,
        bull_case=["trend is aligned", "breakout volume is strong"],
        bear_case=["price is slightly extended"],
        market_evidence=["QQQ remains above SMA20."],
        validation_warnings=["entry zone width 4.00% exceeds warning threshold 3.00%"],
        portfolio_decision="approved",
        portfolio_reason="Approved as the best-ranked semiconductor setup on today's board.",
        raw_score=112.0,
    )
    add_result = make_result(
        "AMD",
        "ADD_TRIGGER",
        "趋势回踩加仓",
        77,
        rating="Overweight",
        setup_type="pullback_add",
        is_actionable=True,
        plan_kind="add",
        entry_zone="$50.00 - $50.50",
        stop="$48.00",
        targets="$54.00 / $56.00",
        position_pct=6.0,
        max_loss_pct=0.5,
        bull_case=["pullback is orderly"],
        bear_case=["needs support to hold"],
        market_evidence=["SMH is still outperforming SPY."],
        portfolio_decision="approved",
        portfolio_reason="Approved as a secondary semiconductor setup.",
    )
    watch_result = make_result(
        "MSFT",
        "WATCH",
        "持有观察",
        58,
        setup_type="hold_watch",
        rating="Hold",
        reasons=["needs cleaner pullback"],
        bull_case=["trend is still intact"],
        bear_case=["entry is not clean enough"],
        portfolio_decision="watchlist",
        portfolio_reason="Not ready for execution today.",
    )
    deferred_result = make_result(
        "AAPL",
        "WATCH",
        "持有观察",
        62,
        setup_type="hold_watch",
        rating="Hold",
        bull_case=["quality trend but crowded sector"],
        bear_case=["better ideas already filled the book"],
        portfolio_decision="deferred",
        portfolio_reason="Deferred because the daily approval limit is already full.",
    )
    risk_result = make_result(
        "TSLA",
        "RISK_REDUCE",
        "减仓/风险升高",
        38,
        setup_type="risk_reduce",
        rating="Underweight",
        reasons=["trend weakening"],
        bull_case=[],
        bear_case=["lost SMA20", "volatility is expanding"],
        portfolio_decision="risk_action",
        portfolio_reason="Reduce exposure and avoid adding risk.",
    )
    reject_result = make_result(
        "QQQ",
        "REJECT",
        "禁止交易/等待",
        72,
        setup_type="breakout_entry",
        rating="No Trade",
        rejection_reasons=["target1 must exceed entry_high"],
        suppressed_by=["trade_plan_validation_failed"],
        portfolio_decision="rejected",
        portfolio_reason="Blocked before portfolio approval.",
    )

    subject, body = compose_daily_report(
        [buy_result, add_result, watch_result, deferred_result, risk_result, reject_result],
        market,
        config,
        datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ),
        ["AAPL deferred after reaching the daily approval limit (2)."],
    )

    assert "Test Brief" in subject
    assert "[Executive Summary]" in body
    assert "[Market Filter]" in body
    assert "[Top Actions]" in body
    assert "[Deferred Ideas]" in body
    assert "[Watch / Wait]" in body
    assert "[Risk Actions]" in body
    assert "[Rejected Plans]" in body
    assert "Sydney 2026-04-20 07:30 / US Eastern 2026-04-19 17:30" in body

    top_actions = section(body, "Top Actions")
    assert "NVDA" in top_actions
    assert "AMD" in top_actions
    assert "rating/action: Buy / BUY_TRIGGER" in top_actions
    assert "score/setup: 100+ / breakout_entry" in top_actions
    assert "market evidence: QQQ remains above SMA20." in top_actions
    assert "validation warning: entry zone width 4.00% exceeds warning threshold 3.00%" in top_actions

    deferred = section(body, "Deferred Ideas")
    assert "AAPL | Hold | 62 | low" in deferred
    assert "quality trend but crowded sector" in deferred
    assert "Deferred because the daily approval limit is already full." in deferred

    watchlist = section(body, "Watch / Wait")
    assert "MSFT | Hold | 58" in watchlist
    assert "AAPL" not in watchlist
    assert "entry_zone" not in watchlist
    assert "position_pct" not in watchlist

    risk_actions = section(body, "Risk Actions")
    assert "TSLA | Underweight | score 38" in risk_actions
    assert "Reduce exposure and avoid adding risk." in risk_actions

    rejected = section(body, "Rejected Plans")
    assert "QQQ | score 72" in rejected
    assert "target1 must exceed entry_high" in rejected
    assert "trade_plan_validation_failed" in rejected

    system_notes = section(body, "System Notes")
    assert "validation warnings:" in system_notes
    assert "portfolio notes:" in system_notes


def test_alert_email_matches_entry_and_risk_styles():
    entry = make_result(
        "NVDA",
        "BUY_TRIGGER",
        "突破入场",
        100,
        rating="Buy",
        setup_type="breakout_entry",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=8.0,
        max_loss_pct=0.4,
        bull_case=["trend is aligned"],
        bear_case=["price is slightly extended"],
        market_evidence=["QQQ remains above SMA20."],
        validation_warnings=["entry zone width 4.00% exceeds warning threshold 3.00%"],
        portfolio_decision="approved",
        portfolio_reason="Approved as the best-ranked setup.",
        raw_score=111.0,
    )
    risk = make_result(
        "TSLA",
        "RISK_REDUCE",
        "减仓/风险升高",
        38,
        rating="Underweight",
        setup_type="risk_reduce",
        bull_case=[],
        bear_case=["lost SMA20"],
        market_evidence=["Growth breadth is fading."],
        portfolio_decision="risk_action",
        portfolio_reason="Reduce exposure and avoid adding risk.",
    )

    entry_subject, entry_body = compose_alert_email(
        entry, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )
    risk_subject, risk_body = compose_alert_email(
        risk, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    assert "Buy / BUY_TRIGGER - score 100+" in entry_subject
    assert "plan:" in entry_body
    assert "why now:" in entry_body
    assert "watch risk:" in entry_body
    assert "validation warning:" in entry_body

    assert "Risk Alert" in risk_subject
    assert "suggested posture:" in risk_body
    assert "No buy/add trade plan is attached to this risk alert." in risk_body


def test_breakout_requires_volume_and_negative_news_can_veto():
    config = make_config()
    tech = TechSnapshot(
        {
            "last": 104.0,
            "high_20": 104.1,
            "sma5": 100.0,
            "sma10": 99.0,
            "sma20": 98.0,
            "atr14": 2.0,
            "rsi14": 58.0,
            "vol_ratio_5": 2.2,
            "close_position": 0.82,
            "dist_ma5_pct": 4.0,
            "dist_ma10_pct": 5.0,
        }
    )
    market = MarketContext("风险偏好", 20.0, [], [], {"QQQ": {"perf20": 5.0}, "SMH": {"perf20": 6.0}})
    positive_news = NewsBundle([], [], {"score": 0.25, "label": "bullish", "sample_size": 3})
    negative_news = NewsBundle([], [], {"score": -0.35, "label": "bearish", "sample_size": 3})

    signal_type, alert_kind = choose_signal_type(tech, None, 72, market, positive_news, config)
    veto_signal_type, veto_alert_kind = choose_signal_type(
        tech, None, 72, market, negative_news, config
    )

    assert signal_type == "突破入场"
    assert alert_kind == "breakout_entry"
    assert veto_signal_type == "禁止交易/等待"
    assert veto_alert_kind == "wait"
