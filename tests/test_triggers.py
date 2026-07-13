from datetime import datetime
from types import SimpleNamespace

from veyraquant.armed_plans import load_plans, save_plans
from veyraquant.timeutils import US_EASTERN_TZ
from veyraquant.triggers import evaluate_plan, run_intraday_check


RTH = datetime(2026, 7, 10, 11, 0, tzinfo=US_EASTERN_TZ)  # Friday 11:00 ET
AFTER_HOURS = datetime(2026, 7, 10, 20, 0, tzinfo=US_EASTERN_TZ)


def make_plan(**overrides):
    plan = {
        "symbol": "NVDA",
        "plan_kind": "buy",
        "setup_type": "breakout_entry",
        "score": 82,
        "entry_low": 100.0,
        "entry_high": 101.0,
        "stop_price": 96.0,
        "target1": 107.5,
        "target2": 112.0,
        "position_pct": 6.4,
        "max_loss_pct": 0.5,
        "created_date": "2026-07-09",
        "expires_date": "2026-07-14",
        "status": "armed",
    }
    plan.update(overrides)
    return plan


def make_config(tmp_path, dry_run=True):
    return SimpleNamespace(
        armed_plans_path=str(tmp_path / "armed.json"),
        dry_run=dry_run,
        smtp=object(),
    )


def test_evaluate_plan_level_rules():
    plan = make_plan()
    assert evaluate_plan(plan, 100.5) == "triggered"      # inside zone
    assert evaluate_plan(plan, 95.0) == "invalidated"     # below stop
    assert evaluate_plan(plan, 96.0) == "invalidated"     # at stop
    assert evaluate_plan(plan, 103.0) is None             # ran away: don't chase
    assert evaluate_plan(plan, 98.0) is None              # between stop and zone


def test_outside_market_hours_never_fetches(tmp_path):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan()])
    calls = []

    run_intraday_check(config, price_fetcher=lambda s: calls.append(s) or 100.5, now_et=AFTER_HOURS)

    assert calls == []
    assert load_plans(config.armed_plans_path)[0]["status"] == "armed"


def test_no_armed_plans_exits_fast(tmp_path):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [])
    calls = []
    run_intraday_check(config, price_fetcher=lambda s: calls.append(s) or 100.5, now_et=RTH)
    assert calls == []


def test_price_in_zone_triggers_once_and_persists(tmp_path, capsys):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan()])

    run_intraday_check(config, price_fetcher=lambda s: 100.5, now_et=RTH)

    stored = load_plans(config.armed_plans_path)[0]
    assert stored["status"] == "triggered"
    assert stored["resolved_price"] == 100.5
    out = capsys.readouterr().out
    assert "TRIGGER" in out and "NVDA" in out

    # One-shot: a second run must not re-alert the resolved plan.
    calls = []
    run_intraday_check(config, price_fetcher=lambda s: calls.append(s) or 100.5, now_et=RTH)
    assert calls == []


def test_price_below_stop_invalidates(tmp_path, capsys):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan()])

    run_intraday_check(config, price_fetcher=lambda s: 95.0, now_et=RTH)

    assert load_plans(config.armed_plans_path)[0]["status"] == "invalidated"
    assert "INVALIDATED" in capsys.readouterr().out


def test_runaway_price_keeps_plan_armed(tmp_path, capsys):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan()])

    run_intraday_check(config, price_fetcher=lambda s: 105.0, now_et=RTH)

    assert load_plans(config.armed_plans_path)[0]["status"] == "armed"
    assert capsys.readouterr().out == ""


def test_expired_plan_is_marked_and_skipped(tmp_path):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan(expires_date="2026-07-09")])
    calls = []

    run_intraday_check(config, price_fetcher=lambda s: calls.append(s) or 100.5, now_et=RTH)

    assert calls == []
    assert load_plans(config.armed_plans_path)[0]["status"] == "expired"


def test_real_send_uses_emailer(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "veyraquant.triggers.send_email", lambda smtp, subject, body: sent.append(subject)
    )
    config = make_config(tmp_path, dry_run=False)
    save_plans(config.armed_plans_path, [make_plan()])

    run_intraday_check(config, price_fetcher=lambda s: 100.5, now_et=RTH)

    assert len(sent) == 1 and "NVDA" in sent[0]


def test_missing_price_leaves_plan_armed_for_retry(tmp_path):
    config = make_config(tmp_path)
    save_plans(config.armed_plans_path, [make_plan()])

    run_intraday_check(config, price_fetcher=lambda s: None, now_et=RTH)

    assert load_plans(config.armed_plans_path)[0]["status"] == "armed"


# --- pre-market readiness digest (never uses extended-hours quotes) ---

PREMARKET_NOW = datetime(2026, 7, 10, 9, 5, tzinfo=US_EASTERN_TZ)  # Fri, before open


def test_premarket_digest_reports_distance_never_fires(tmp_path, capsys):
    config = make_config(tmp_path)
    config.premarket_briefing_enabled = True
    save_plans(config.armed_plans_path, [
        make_plan(symbol="NVDA", entry_low=100.0, entry_high=101.0, stop_price=96.0),
        make_plan(symbol="AMD", entry_low=50.0, entry_high=51.0, stop_price=48.0),
    ])
    # Prior closes: NVDA 0.5% below its zone, AMD sitting inside its zone.
    closes = {"NVDA": 99.5, "AMD": 50.5}

    from veyraquant.triggers import run_premarket_briefing
    run_premarket_briefing(config, close_fetcher=lambda s: closes[s], now_et=PREMARKET_NOW)

    out = capsys.readouterr().out
    assert "Pre-market readiness" in out
    assert "NVDA" in out and "AMD" in out
    assert "INSIDE the entry zone" in out          # AMD
    assert "below the entry zone" in out           # NVDA 0.5% below
    # Plan status is NEVER changed by the briefing.
    plans = load_plans(config.armed_plans_path)
    assert all(p["status"] == "armed" for p in plans)


def test_premarket_row_computes_distance_and_flags():
    from veyraquant.triggers import _premarket_row

    plan = make_plan(entry_low=100.0, entry_high=101.0, stop_price=96.0)
    assert _premarket_row(plan, 98.0)["dist_to_entry_pct"] == round((100.0 - 98.0) / 98.0 * 100, 2)
    assert _premarket_row(plan, 100.5)["in_zone"] is True
    assert _premarket_row(plan, 100.5)["dist_to_entry_pct"] == 0.0
    assert _premarket_row(plan, 95.0)["below_stop"] is True
    assert _premarket_row(plan, None)["dist_to_entry_pct"] is None   # no close, no guess


def test_premarket_disabled_or_no_plans_sends_nothing(tmp_path, capsys):
    from veyraquant.triggers import run_premarket_briefing

    off = make_config(tmp_path)
    off.premarket_briefing_enabled = False
    save_plans(off.armed_plans_path, [make_plan()])
    run_premarket_briefing(off, close_fetcher=lambda s: 100.0, now_et=PREMARKET_NOW)
    assert capsys.readouterr().out == ""

    on_empty = make_config(tmp_path)
    on_empty.premarket_briefing_enabled = True
    save_plans(on_empty.armed_plans_path, [])
    run_premarket_briefing(on_empty, close_fetcher=lambda s: 100.0, now_et=PREMARKET_NOW)
    assert capsys.readouterr().out == ""


def test_premarket_real_send_uses_emailer(tmp_path, monkeypatch):
    from veyraquant.triggers import run_premarket_briefing

    sent = []
    monkeypatch.setattr("veyraquant.triggers.send_email", lambda smtp, subject, body: sent.append(subject))
    config = make_config(tmp_path, dry_run=False)
    config.premarket_briefing_enabled = True
    save_plans(config.armed_plans_path, [make_plan(symbol="NVDA")])

    run_premarket_briefing(config, close_fetcher=lambda s: 100.5, now_et=PREMARKET_NOW)
    assert len(sent) == 1 and "readiness" in sent[0]


def test_premarket_only_sends_in_the_9am_et_window(tmp_path, capsys):
    from veyraquant.triggers import run_premarket_briefing

    config = make_config(tmp_path)
    config.premarket_briefing_enabled = True
    save_plans(config.armed_plans_path, [make_plan()])

    # 14:00 UTC on a summer (EDT) day = 10:00 ET -> outside the window, skip
    # (the 13:00 UTC run that day is 09:00 ET and would be the one that sends).
    ten_et = datetime(2026, 7, 10, 10, 0, tzinfo=US_EASTERN_TZ)
    run_premarket_briefing(config, close_fetcher=lambda s: 100.5, now_et=ten_et)
    assert capsys.readouterr().out == ""

    # Weekend never sends.
    sat = datetime(2026, 7, 11, 9, 5, tzinfo=US_EASTERN_TZ)
    run_premarket_briefing(config, close_fetcher=lambda s: 100.5, now_et=sat)
    assert capsys.readouterr().out == ""

    # 09:05 ET on a weekday sends.
    run_premarket_briefing(config, close_fetcher=lambda s: 100.5, now_et=PREMARKET_NOW)
    assert "Pre-market readiness" in capsys.readouterr().out
