from datetime import datetime, timedelta, timezone

from veyraquant.state import (
    STATE_VERSION,
    alert_in_cooldown,
    mark_alert_sent,
    mark_daily_sent,
    migrate_state,
    should_send_alert,
)


def test_migrate_legacy_daily_state():
    state = migrate_state({"date": "2026-03-03", "sent_at": "2026-03-03T07:33:21+11:00"})

    assert state["version"] == STATE_VERSION
    assert state["daily"]["date"] == "2026-03-03"
    assert state["alerts"] == {}


def test_alert_cooldown_by_symbol_and_kind():
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    state = migrate_state({})
    mark_daily_sent(state, now)
    mark_alert_sent(state, "NVDA", "breakout_entry", now, {"score": 70})

    assert alert_in_cooldown(state, "NVDA", "breakout_entry", now + timedelta(hours=1), 12)
    assert not alert_in_cooldown(state, "MSFT", "breakout_entry", now + timedelta(hours=1), 12)
    assert not alert_in_cooldown(state, "NVDA", "breakout_entry", now + timedelta(hours=13), 12)


def test_should_send_alert_blocks_same_signal_hash_within_cooldown():
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    state = migrate_state({})
    mark_alert_sent(state, "NVDA", "breakout_entry", now, {"score": 70, "signal_hash": "abc"})

    should_send, reason = should_send_alert(
        state,
        "NVDA",
        "breakout_entry",
        now + timedelta(hours=1),
        12,
        signal_hash="abc",
    )

    assert not should_send
    assert reason == "cooldown_active"


def test_should_send_alert_allows_changed_signal_hash_within_cooldown():
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    state = migrate_state({})
    mark_alert_sent(state, "NVDA", "breakout_entry", now, {"score": 70, "signal_hash": "abc"})

    should_send, reason = should_send_alert(
        state,
        "NVDA",
        "breakout_entry",
        now + timedelta(hours=1),
        12,
        signal_hash="xyz",
    )

    assert should_send
    assert reason == "signal_materially_changed"


def test_should_send_alert_handles_legacy_state_without_signal_hash():
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    state = migrate_state({})
    mark_alert_sent(state, "NVDA", "breakout_entry", now, {"score": 70})

    should_send, reason = should_send_alert(
        state,
        "NVDA",
        "breakout_entry",
        now + timedelta(hours=1),
        12,
        signal_hash="xyz",
    )

    assert not should_send
    assert reason == "cooldown_active"


# --- R3.5: two-level fingerprint semantics ---

def test_identity_change_bypasses_cooldown_with_its_own_reason():
    state = {"alerts": {"NVDA": {"breakout_entry": {
        "sent_at": "2026-05-01T10:00:00+10:00",
        "signal_hash": "mat-1", "identity_hash": "id-1",
    }}}}
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("Australia/Sydney"))

    from veyraquant.state import should_send_alert
    send, reason = should_send_alert(
        state, "NVDA", "breakout_entry", now, 12, "mat-1", identity_hash="id-2"
    )
    assert send and reason == "signal_identity_changed"


def test_same_material_state_holds_cooldown_and_legacy_state_still_works():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from veyraquant.state import should_send_alert

    now = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    # Legacy record: no identity_hash stored -> identity check is skipped.
    legacy = {"alerts": {"NVDA": {"breakout_entry": {
        "sent_at": "2026-05-01T10:00:00+10:00", "signal_hash": "mat-1",
    }}}}
    send, reason = should_send_alert(
        legacy, "NVDA", "breakout_entry", now, 12, "mat-1", identity_hash="id-1"
    )
    assert not send and reason == "cooldown_active"

    send, reason = should_send_alert(
        legacy, "NVDA", "breakout_entry", now, 12, "mat-2", identity_hash="id-1"
    )
    assert send and reason == "signal_materially_changed"
