import os

import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.data import DataClient, headline_sentiment_score
from veyraquant.models import DataQuality


def make_config(tmp_path):
    return AppConfig(
        symbols=["NVDA"],
        market_symbols=["SPY"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=10,
        state_path=str(tmp_path / "state.json"),
        cache_dir=str(tmp_path / "cache"),
        subject_prefix="Test",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=None,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=3,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def cached_price_frame():
    return pd.DataFrame(
        {
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
        },
        index=pd.date_range("2026-01-01", periods=2),
    )


class BrokenTicker:
    def history(self, **_kwargs):
        raise RuntimeError("network down")


def test_headline_sentiment_score_detects_keywords():
    assert headline_sentiment_score("NVDA bullish breakout after strong AI growth") > 0
    assert headline_sentiment_score("NVDA warning after weak downgrade risk") < 0


def test_price_history_falls_back_to_cache(tmp_path):
    config = make_config(tmp_path)
    client = DataClient(config)
    cache = tmp_path / "cache" / "NVDA_daily.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cached_price_frame().to_csv(cache)

    warnings = []
    loaded = client._fetch_history("NVDA", BrokenTicker(), "daily", "1y", "1d", warnings)

    assert loaded is not None
    assert loaded["Close"].iloc[-1] == 102
    assert warnings


def test_stale_daily_cache_marks_data_quality_low(tmp_path):
    config = make_config(tmp_path)
    client = DataClient(config)
    cache = tmp_path / "cache" / "NVDA_daily.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cached_price_frame().to_csv(cache)
    stale_time = pd.Timestamp.now().timestamp() - 80 * 3600
    os.utime(cache, (stale_time, stale_time))

    warnings = []
    quality = DataQuality()
    loaded = client._fetch_history(
        "NVDA", BrokenTicker(), "daily", "1y", "1d", warnings, quality
    )
    client._finalize_data_quality("NVDA", quality, warnings)

    assert loaded is not None
    assert quality.price_freshness == "cache"
    assert quality.data_quality_level == "LOW"
    assert not quality.actionable_allowed
    assert any("threshold" in reason for reason in quality.reasons)


def test_trim_drops_todays_daily_bar_before_close():
    from datetime import datetime
    from veyraquant.data import trim_incomplete_bars
    from veyraquant.timeutils import US_EASTERN_TZ

    idx = pd.date_range("2026-07-06", periods=5, freq="B")  # Mon..Fri
    frame = pd.DataFrame(
        {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 100.0},
        index=idx,
    )
    # Friday 10:30 ET, market open: Friday's live bar must be dropped.
    intraday_now = datetime(2026, 7, 10, 10, 30, tzinfo=US_EASTERN_TZ)
    trimmed = trim_incomplete_bars(frame, "1d", now_et=intraday_now)
    assert len(trimmed) == 4
    assert trimmed.index[-1].date().isoformat() == "2026-07-09"

    # Friday 16:05 ET, after the close: the bar is complete, keep it.
    after_close = datetime(2026, 7, 10, 16, 5, tzinfo=US_EASTERN_TZ)
    kept = trim_incomplete_bars(frame, "1d", now_et=after_close)
    assert len(kept) == 5

    # Saturday: yesterday's bar is complete, keep everything.
    weekend = datetime(2026, 7, 11, 9, 0, tzinfo=US_EASTERN_TZ)
    assert len(trim_incomplete_bars(frame, "1d", now_et=weekend)) == 5


def test_trim_drops_forming_intraday_bar_only():
    from datetime import datetime
    from veyraquant.data import trim_incomplete_bars
    from veyraquant.timeutils import US_EASTERN_TZ

    idx = pd.date_range("2026-07-10 09:30", periods=4, freq="30min", tz="America/New_York")
    frame = pd.DataFrame(
        {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 100.0},
        index=idx,
    )
    # 11:10 ET: the 11:00 bar is still forming -> drop it.
    mid_bar = datetime(2026, 7, 10, 11, 10, tzinfo=US_EASTERN_TZ)
    trimmed = trim_incomplete_bars(frame, "30m", now_et=mid_bar)
    assert len(trimmed) == 3

    # 11:31 ET: the 11:00 bar has closed -> keep all four.
    after_bar = datetime(2026, 7, 10, 11, 31, tzinfo=US_EASTERN_TZ)
    assert len(trim_incomplete_bars(frame, "30m", now_et=after_bar)) == 4


def test_trim_handles_empty_and_unknown_interval():
    from datetime import datetime
    from veyraquant.data import trim_incomplete_bars
    from veyraquant.timeutils import US_EASTERN_TZ

    now = datetime(2026, 7, 10, 11, 10, tzinfo=US_EASTERN_TZ)
    assert trim_incomplete_bars(None, "1d", now_et=now) is None
    frame = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
        index=pd.date_range("2026-07-10 09:30", periods=1, freq="30min", tz="America/New_York"),
    )
    # Unknown interval string: be conservative and keep the data untouched.
    assert len(trim_incomplete_bars(frame, "weird", now_et=now)) == 1
