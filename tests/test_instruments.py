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
