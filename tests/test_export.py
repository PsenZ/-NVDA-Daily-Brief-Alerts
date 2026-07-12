import json
from datetime import datetime

from veyraquant.export import (
    build_brief_payload,
    export_armed_plans,
    export_daily_brief,
    export_decisions,
)
from veyraquant.models import MarketContext
from veyraquant.timeutils import SYDNEY_TZ

from test_signals_reporting import make_config, make_result


def sample_market():
    return MarketContext(
        label="风险偏好",
        score=18.0,
        reasons=["SPY above SMA20"],
        risks=["QQQ momentum fading"],
        snapshots={"SPY": {"last": 161.2, "perf20": 7.48}, "^VIX": {"last": 16.35}},
    )


def sample_results():
    approved = make_result(
        "NVDA", "BUY_TRIGGER", "breakout", 82, setup_type="breakout_entry",
        rating="Buy", is_actionable=True, plan_kind="buy",
        entry_zone="$100.00 - $101.00", stop="$96.00", targets="$107.50 / $112.00",
        position_pct=6.4, max_loss_pct=0.5,
        portfolio_decision="approved", portfolio_reason="Approved.",
    )
    approved.trade_plan.entry_low = 100.0
    approved.trade_plan.entry_high = 101.0
    approved.trade_plan.stop_price = 96.0
    approved.trade_plan.target1 = 107.5
    approved.trade_plan.target2 = 112.0
    watch = make_result("AAPL", "WATCH", "hold", 58, portfolio_decision="watchlist")
    return [approved, watch]


def test_brief_payload_is_json_serializable_with_expected_shape():
    now = datetime(2026, 7, 12, 7, 35, tzinfo=SYDNEY_TZ)
    payload = build_brief_payload(
        sample_results(), sample_market(), make_config(), now, ["note"], ["review"]
    )

    json.dumps(payload)  # must not raise
    assert payload["schema_version"] == 1
    assert payload["date"] == "2026-07-12"
    assert payload["meta"]["symbols"] == ["NVDA", "MSFT"]
    assert payload["meta"]["market_symbols"] == ["SPY", "QQQ", "SMH", "^VIX"]
    assert payload["summary"] == {
        "trading_posture": "Selective execution",
        "approved": 1,
        "deferred": 0,
        "watchlist": 1,
        "risk_actions": 0,
        "rejected": 0,
    }
    nvda = payload["results"][0]
    assert nvda["symbol"] == "NVDA"
    assert nvda["plan"]["entry_low"] == 100.0
    assert nvda["plan"]["stop_price"] == 96.0
    assert nvda["contributions"] == {"trend": 10.0}


def test_export_daily_brief_writes_archive_latest_and_index(tmp_path):
    export_dir = str(tmp_path / "data")
    now = datetime(2026, 7, 12, 7, 35, tzinfo=SYDNEY_TZ)
    payload = build_brief_payload(sample_results(), sample_market(), make_config(), now)

    export_daily_brief(export_dir, payload)
    export_daily_brief(export_dir, payload)  # idempotent for the same date

    archive = json.loads((tmp_path / "data" / "briefs" / "2026-07-12.json").read_text("utf-8"))
    latest = json.loads((tmp_path / "data" / "latest.json").read_text("utf-8"))
    index = json.loads((tmp_path / "data" / "index.json").read_text("utf-8"))
    assert archive["date"] == latest["date"] == "2026-07-12"
    assert index["dates"] == ["2026-07-12"]

    payload2 = dict(payload, date="2026-07-13")
    export_daily_brief(export_dir, payload2)
    index = json.loads((tmp_path / "data" / "index.json").read_text("utf-8"))
    assert index["dates"] == ["2026-07-12", "2026-07-13"]


def test_export_decisions_mirrors_jsonl(tmp_path):
    log = tmp_path / "decision_log.jsonl"
    log.write_text('{"symbol": "NVDA", "outcome_status": "resolved"}\n', encoding="utf-8")
    export_dir = str(tmp_path / "data")

    export_decisions(export_dir, str(log))

    mirrored = json.loads((tmp_path / "data" / "decisions.json").read_text("utf-8"))
    assert mirrored["entries"] == [{"symbol": "NVDA", "outcome_status": "resolved"}]


def test_export_armed_plans_writes_mirror(tmp_path):
    export_dir = str(tmp_path / "data")
    plans = [{"symbol": "NVDA", "status": "armed"}]

    export_armed_plans(export_dir, plans)

    mirrored = json.loads((tmp_path / "data" / "armed_plans.json").read_text("utf-8"))
    assert mirrored["plans"] == plans
