"""Golden-file snapshot for the plain-text daily brief.

Locks the plain-text output byte-for-byte so the M2/M3 HTML restructure
cannot silently change the plain-text content. Regenerate intentionally with
UPDATE_SNAPSHOT=1 pytest tests/test_report_snapshot.py and review the diff.
"""
import os
from datetime import datetime
from pathlib import Path

from veyraquant.models import MarketContext
from veyraquant.reporting import compose_daily_report
from veyraquant.timeutils import SYDNEY_TZ

from test_signals_reporting import make_config, make_result


GOLDEN = Path(__file__).parent / "snapshots" / "daily_brief.txt"


def _comprehensive_report():
    config = make_config()
    market = MarketContext(
        label="风险偏好",
        score=18.0,
        reasons=["SPY 位于 SMA20/SMA50 上方，市场背景偏多", "SMH 半导体强度支撑科技延续"],
        risks=["QQQ 短线动能转弱"],
        snapshots={
            "SPY": {"last": 161.2, "sma20": 153.4, "sma50": 152.4, "perf20": 7.48},
            "QQQ": {"last": 156.4, "sma20": 156.8, "sma50": 156.1, "perf20": -0.33},
            "SMH": {"last": 177.1, "sma20": 176.0, "sma50": 171.4, "perf20": 3.96},
            "^VIX": {"last": 16.35},
        },
    )
    results = [
        make_result(
            "NVDA", "BUY_TRIGGER", "breakout", 82,
            setup_type="breakout_entry", rating="Buy", is_actionable=True,
            plan_kind="buy", entry_zone="$182.40 - $185.10", stop="$176.20",
            targets="$196.50 / $210.80", position_pct=6.4, max_loss_pct=0.5,
            bull_case=["MACD above signal, histogram expanding.", "Relative strength beats SPY/QQQ."],
            bear_case=["Breakout can fail below SMA20."],
            portfolio_decision="approved", portfolio_reason="Approved within risk budget.",
        ),
        make_result(
            "MSFT", "ADD_TRIGGER", "pullback", 71,
            setup_type="pullback_add", rating="Overweight", is_actionable=True,
            plan_kind="add", entry_zone="$410.00 - $413.00", stop="$402.00",
            targets="$426.00 / $440.00", position_pct=5.0, max_loss_pct=0.4,
            bull_case=["Healthy pullback to MA10."],
            portfolio_decision="deferred",
            portfolio_reason="Deferred after reaching the daily approval limit (3).",
        ),
        make_result(
            "AAPL", "WATCH", "hold_watch", 58,
            setup_type="hold_watch", rating="Hold",
            portfolio_decision="watchlist", portfolio_reason="Not ready for execution today.",
        ),
        make_result(
            "TSLA", "RISK_REDUCE", "risk_reduce", 38,
            setup_type="risk_reduce", rating="Underweight",
            risks=["RSI overheated above 74.", "Price extended far above MA5."],
            bear_case=["RSI overheated above 74.", "Price extended far above MA5."],
            portfolio_decision="risk_action",
            portfolio_reason="Risk control takes priority over new exposure.",
        ),
        make_result(
            "AMD", "REJECT", "wait", 40,
            setup_type="wait", rating="No Trade",
            rejection_reasons=["Trade plan validation failed."],
            suppressed_by=["trade_plan_validation_failed"],
            portfolio_decision="rejected", portfolio_reason="Blocked before approval.",
        ),
    ]
    now = datetime(2026, 7, 10, 7, 35, tzinfo=SYDNEY_TZ)
    portfolio_notes = ["Neutral market regime caps approved trades to 3."]
    review_notes = ["setup_type:breakout_entry avg 5D alpha +1.20% over 4 resolved decision(s)."]
    _subject, body = compose_daily_report(results, market, config, now, portfolio_notes, review_notes)
    return body


def test_plain_text_daily_brief_matches_snapshot():
    body = _comprehensive_report()
    if os.getenv("UPDATE_SNAPSHOT") == "1" or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(body, encoding="utf-8")
    expected = GOLDEN.read_text(encoding="utf-8")
    assert body == expected, (
        "Plain-text daily brief changed. If intentional, regenerate with "
        "UPDATE_SNAPSHOT=1 and review the diff."
    )
