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
