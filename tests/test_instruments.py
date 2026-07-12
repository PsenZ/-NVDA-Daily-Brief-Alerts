import json

from veyraquant.instruments import (
    DEFAULT_MIN_AVG_DOLLAR_VOLUME,
    default_profile,
    load_registry,
    resolve_profile,
)


def test_crypto_inference_disables_equity_rules():
    profile = default_profile("BTC-USD")
    assert profile.asset_type == "crypto"
    assert profile.has_options is False
    assert profile.has_fundamentals is False
    assert profile.min_avg_dollar_volume is None
    assert profile.sector == "crypto"


def test_index_inference():
    profile = default_profile("^VIX")
    assert profile.asset_type == "index"
    assert profile.has_options is False
    assert profile.has_fundamentals is False


def test_unknown_ticker_gets_conservative_stock_defaults():
    profile = default_profile("ZZZZ")
    assert profile.asset_type == "stock"
    assert profile.has_options and profile.has_fundamentals
    assert profile.is_leveraged is False
    assert profile.min_history_bars == 60
    assert profile.min_avg_dollar_volume == DEFAULT_MIN_AVG_DOLLAR_VOLUME


def test_builtin_watchlist_reproduces_legacy_resonance_wiring():
    nvda = default_profile("NVDA")
    assert nvda.sector == "semiconductor"
    assert nvda.sector_benchmark == "SMH"
    assert nvda.qqq_sensitive is True
    amd = default_profile("AMD")
    assert amd.sector_benchmark == "SMH" and amd.qqq_sensitive is False
    tsla = default_profile("TSLA")
    assert tsla.sector_benchmark is None and tsla.qqq_sensitive is True


def test_leveraged_and_inverse_flags():
    assert default_profile("TQQQ").is_leveraged is True
    sqqq = default_profile("SQQQ")
    assert sqqq.is_leveraged and sqqq.is_inverse


def test_json_overrides_merge_over_builtins(tmp_path):
    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "nvda": {"min_avg_dollar_volume": 123.0},
                "NEWCO": {"asset_type": "stock", "is_adr": True, "min_history_bars": 120},
                "_comment": "ignored string entry",
                "BAD": "not-a-dict",
            }
        ),
        encoding="utf-8",
    )
    registry = load_registry(str(path))

    nvda = resolve_profile("NVDA", registry)
    assert nvda.min_avg_dollar_volume == 123.0
    assert nvda.sector_benchmark == "SMH"  # builtin fields survive the merge

    newco = resolve_profile("NEWCO", registry)
    assert newco.is_adr is True and newco.min_history_bars == 120

    assert resolve_profile("BAD", registry).asset_type == "stock"  # inferred


def test_missing_registry_file_falls_back_to_builtins(tmp_path):
    registry = load_registry(str(tmp_path / "nope.json"))
    assert resolve_profile("TQQQ", registry).is_leveraged is True


# --- acceptance: policy vetoes and resonance wiring through the pipeline ---

def _analyze(symbol, profile=None, daily=None, monkeypatch=None):
    from veyraquant.signals import analyze_symbol
    from veyraquant.models import FundamentalsData
    from test_signal_consistency import (
        breakout_snapshot, bullish_market, dummy_daily, make_config, news_bundle, score_result,
    )

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _d: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _i: None)
    monkeypatch.setattr(
        "veyraquant.signals.score_components", lambda *a, **k: score_result(72)
    )
    return analyze_symbol(
        symbol,
        dummy_daily() if daily is None else daily,
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
        profile=profile,
    )


def test_leveraged_etf_is_vetoed_from_actionable(monkeypatch):
    result = _analyze("TQQQ", profile=default_profile("TQQQ"), monkeypatch=monkeypatch)
    assert result.action == "WATCH"
    assert "leveraged_product_policy" in result.suppressed_by
    assert not result.is_actionable


def test_illiquid_symbol_is_vetoed(monkeypatch):
    from dataclasses import replace
    from test_signal_consistency import dummy_daily

    thin = dummy_daily()
    thin["Volume"] = 100.0  # ~ $10-15k ADV, far under the $5M floor
    profile = replace(default_profile("ZZZZ"))
    result = _analyze("ZZZZ", profile=profile, daily=thin, monkeypatch=monkeypatch)
    assert result.action == "WATCH"
    assert "insufficient_liquidity" in result.suppressed_by


def test_recent_ipo_history_gate(monkeypatch):
    from dataclasses import replace

    profile = replace(default_profile("NEWIPO"), min_history_bars=120)
    result = _analyze("NEWIPO", profile=profile, monkeypatch=monkeypatch)  # 100 bars
    assert result.action == "WAIT"
    assert "insufficient_daily_data" in result.suppressed_by


def test_crypto_flows_without_equity_rules(monkeypatch):
    result = _analyze("BTC-USD", profile=default_profile("BTC-USD"), monkeypatch=monkeypatch)
    # No liquidity floor, no leverage flag -> the breakout stands on its own.
    assert result.action == "BUY_TRIGGER"
    assert result.sector_bucket == "crypto"


def test_sector_resonance_is_registry_driven():
    from veyraquant.models import FundamentalsData, TechSnapshot
    from veyraquant.scoring import score_components
    from test_signal_consistency import bullish_market, news_bundle

    full_snapshot = TechSnapshot(
        {
            "last": 104.0, "sma5": 100.0, "sma10": 99.0, "sma20": 98.0,
            "sma50": 96.0, "sma200": 90.0, "rsi14": 58.0, "macd": 1.0,
            "signal": 0.8, "macd_hist": 0.2, "macd_hist_prev": 0.1,
            "high_55": 105.0, "adx14": 28.0, "plus_di": 30.0, "minus_di": 15.0,
            "vol_ratio": 1.2, "vol_ratio_5": 2.2, "atr_pct": 2.0,
            "perf20": 6.0, "dist_ma5_pct": 4.0, "dist_ma10_pct": 5.0,
        }
    )

    def resonance(symbol):
        contributions, _r, _k = score_components(
            symbol, full_snapshot, FundamentalsData(), None,
            news_bundle(0.0), bullish_market(),
        )
        return contributions["sector_resonance"]

    assert resonance("NVDA") == 7   # SMH +4 and QQQ +3 (legacy behavior)
    assert resonance("AMD") == 4    # SMH only
    assert resonance("TSLA") == 3   # QQQ only
    assert resonance("ZZZZ") == 0   # unknown ticker: neutral
