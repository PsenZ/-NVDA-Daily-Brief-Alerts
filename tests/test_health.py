import json
from types import SimpleNamespace

from veyraquant.health import build_run_manifest, intraday_heartbeat, write_health
from veyraquant.models import DataQuality


def result_with(freshness, warnings=0, level="HIGH"):
    return SimpleNamespace(
        symbol="X",
        data_quality=DataQuality(price_freshness=freshness, data_quality_level=level),
        warnings=["w"] * warnings,
    )


def test_manifest_counts_live_cache_failed_and_rates():
    results = [
        result_with("live"), result_with("live"),
        result_with("cache", warnings=2, level="MEDIUM"),
        result_with("missing", level="LOW"),
    ]
    manifest = build_run_manifest(
        results, started_at="s", finished_at="f", duration_seconds=12.345,
        data_fetch_seconds=3.21, email_sent=True, alerts_sent=2, export_ok=True,
    )
    assert manifest["symbols_processed"] == 4
    assert manifest["symbols_live"] == 2
    assert manifest["symbols_cache"] == 1
    assert manifest["symbols_failed"] == 1
    assert manifest["cache_hit_rate_pct"] == 25.0
    assert manifest["email_sent"] is True and manifest["alerts_sent"] == 2
    assert manifest["export_ok"] is True
    assert manifest["duration_seconds"] == 12.35
    assert manifest["symbols"][2]["warnings"] == 2


def test_write_health_daily_preserves_intraday_heartbeat(tmp_path):
    export_dir = str(tmp_path)
    beat = intraday_heartbeat(checked_plans=3, transitions=1, started_at="hb", duration_seconds=0.5)
    assert write_health(export_dir, beat) is True

    daily = build_run_manifest([], "s", "f", 1.0, email_sent=False)
    assert write_health(export_dir, daily) is True

    payload = json.loads((tmp_path / "health.json").read_text("utf-8"))
    assert payload["run_kind"] == "daily"                       # daily owns top level
    assert payload["intraday_heartbeat"]["checked_plans"] == 3  # heartbeat survives
    assert payload["intraday_heartbeat"]["transitions"] == 1

    # A later heartbeat updates its section without clobbering the daily run.
    beat2 = intraday_heartbeat(checked_plans=5, transitions=0, started_at="hb2", duration_seconds=0.2)
    write_health(export_dir, beat2)
    payload = json.loads((tmp_path / "health.json").read_text("utf-8"))
    assert payload["run_kind"] == "daily"
    assert payload["intraday_heartbeat"]["checked_plans"] == 5


def test_write_health_disabled_or_broken_never_raises(tmp_path):
    assert write_health("", {"run_kind": "daily"}) is False
    bad = tmp_path / "health.json"
    bad.write_text("not-json", encoding="utf-8")
    # Corrupt existing file: overwritten cleanly, still returns True.
    assert write_health(str(tmp_path), build_run_manifest([], "s", "f", 1.0)) is True
