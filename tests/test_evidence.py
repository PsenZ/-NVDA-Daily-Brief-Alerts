"""R3 acceptance: every score point is traceable to an evidence item."""
from collections import defaultdict

from veyraquant.evidence import GATE_REGISTRY, KNOWN_CODES, gate_evidence
from veyraquant.models import FundamentalsData, NewsBundle, OptionsData, TechSnapshot
from veyraquant.scoring import score_components

from test_signal_consistency import bullish_market


def full_snapshot(**overrides):
    values = {
        "last": 104.0, "sma5": 100.0, "sma10": 99.0, "sma20": 98.0,
        "sma50": 96.0, "sma200": 90.0, "rsi14": 58.0, "macd": 1.0,
        "signal": 0.8, "macd_hist": 0.2, "macd_hist_prev": 0.1,
        "high_55": 105.0, "adx14": 28.0, "plus_di": 30.0, "minus_di": 15.0,
        "vol_ratio": 1.2, "vol_ratio_5": 2.2, "atr_pct": 2.0,
        "perf20": 6.0, "dist_ma5_pct": 4.0, "dist_ma10_pct": 5.0,
    }
    values.update(overrides)
    return TechSnapshot(values)


def rich_inputs():
    fundamentals = FundamentalsData(recommendation_key="sell", revenue_growth=-0.1)
    options = OptionsData(expiration="2026-08-21", put_call_oi=1.0, put_call_vol=1.5, iv_mid=0.7)
    news = NewsBundle(
        [{"title": "x", "link": "y"}], [],
        {"score": -0.3, "label": "bearish", "sample_size": 3},
    )
    return fundamentals, options, news


def test_every_point_traces_to_evidence_and_sums_match():
    fundamentals, options, news = rich_inputs()
    contributions, reasons, risks, evidence = score_components(
        "NVDA", full_snapshot(), fundamentals, options, news, bullish_market()
    )

    # 1) every emitted code is registered
    assert all(item.code in KNOWN_CODES for item in evidence)

    # 2) per-component point sums equal the contribution values exactly
    sums: dict[str, float] = defaultdict(float)
    for item in evidence:
        if item.points is not None:
            sums[item.component] += item.points
    for component, value in contributions.items():
        assert abs(sums[component] - value) < 1e-9, (
            f"{component}: evidence sums to {sums[component]}, contribution is {value}"
        )

    # 3) narrative lists are exactly the evidence-derived texts, in order
    assert reasons == [item.text for item in evidence if item.polarity == "reason"]
    assert risks == [item.text for item in evidence if item.polarity == "risk"]


def test_measured_values_ride_along():
    contributions, _r, _k, evidence = score_components(
        "NVDA", full_snapshot(rsi14=80.0), FundamentalsData(), None,
        NewsBundle([], [], {"score": 0.0, "label": "x", "sample_size": 0}),
        bullish_market(),
    )
    overheated = [item for item in evidence if item.code == "MOM_RSI_OVERHEATED"]
    assert overheated and overheated[0].value == 80.0
    assert overheated[0].points == -7


def test_gate_registry_covers_all_suppression_codes_and_analyze_attaches_them(monkeypatch):
    from veyraquant.models import DataQuality
    from veyraquant.signals import analyze_symbol
    from test_signal_consistency import (
        breakout_snapshot, dummy_daily, make_config, news_bundle, score_result,
    )

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _d: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _i: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *a, **k: score_result(72))

    result = analyze_symbol(
        "NVDA", dummy_daily(), None, FundamentalsData(days_to_earnings=1), None,
        news_bundle(0.0), bullish_market(), make_config(),
    )
    assert "earnings_blackout" in result.suppressed_by
    gate_codes = {item.code for item in result.evidence if item.component == "gate"}
    assert "EARNINGS_BLACKOUT" in gate_codes

    # every suppression code appearing anywhere maps into the registry
    for code in result.suppressed_by:
        assert code in GATE_REGISTRY


def test_gate_evidence_unknown_code_still_produces_item():
    item = gate_evidence("some_future_code")
    assert item.code == "SOME_FUTURE_CODE"
    assert item.polarity == "risk" and item.component == "gate"


# --- R3.5: broad vs sector relative strength ---

def _rs(symbol, perf20, snapshots):
    from veyraquant.models import MarketContext

    market = MarketContext("risk-on", 10.0, ["x"], [], snapshots)
    contributions, _r, _k, evidence = score_components(
        symbol, full_snapshot(perf20=perf20), FundamentalsData(), None,
        NewsBundle([], [], {"score": 0.0, "label": "x", "sample_size": 0}), market,
    )
    codes = {item.code for item in evidence}
    return contributions, codes


def test_sector_outperform_and_lag_are_relative_to_the_benchmark():
    snaps = {"SPY": {"perf20": 2.0}, "SMH": {"perf20": 4.0}}
    contributions, codes = _rs("NVDA", 10.0, snaps)   # +10 vs SMH +4 -> +6 spread
    assert contributions["relative_strength_sector"] == 6
    assert "RS_SECTOR_OUTPERFORM" in codes
    assert contributions["relative_strength_broad"] == 6  # +10 vs SPY +2

    contributions, codes = _rs("AMD", 4.0, {"SPY": {"perf20": 2.0}, "SMH": {"perf20": 10.0}})
    assert contributions["relative_strength_sector"] == -6  # +4 vs SMH +10
    assert "RS_SECTOR_LAG" in codes


def test_non_tech_symbols_compare_to_their_own_sector_etf():
    jpm, codes_jpm = _rs("JPM", 8.0, {"SPY": {"perf20": 2.0}, "XLF": {"perf20": 1.0}})
    assert jpm["relative_strength_sector"] == 6
    assert "RS_SECTOR_OUTPERFORM" in codes_jpm

    xom, codes_xom = _rs("XOM", -2.0, {"SPY": {"perf20": 2.0}, "XLE": {"perf20": 5.0}})
    assert xom["relative_strength_sector"] == -6
    assert "RS_SECTOR_LAG" in codes_xom

    meta, codes_meta = _rs("META", 5.0, {"SPY": {"perf20": 2.0}, "XLC": {"perf20": 4.0}})
    assert meta["relative_strength_sector"] == 0
    assert "RS_SECTOR_NEUTRAL" in codes_meta


def test_no_sector_benchmark_means_broad_only():
    contributions, codes = _rs("ZZZZ", 10.0, {"SPY": {"perf20": 2.0}})
    assert contributions["relative_strength_broad"] == 6
    assert contributions["relative_strength_sector"] == 0
    assert not any(code.startswith("RS_SECTOR") for code in codes)


def test_sector_etf_never_compares_to_itself():
    contributions, codes = _rs("SMH", 8.0, {"SPY": {"perf20": 2.0}, "SMH": {"perf20": 8.0}})
    assert contributions["relative_strength_sector"] == 0
    assert not any(code.startswith("RS_SECTOR") for code in codes)


def test_missing_benchmark_data_records_unavailable_without_scoring():
    contributions, codes = _rs("NVDA", 10.0, {"SPY": {"perf20": 2.0}})  # no SMH snapshot
    assert contributions["relative_strength_sector"] == 0
    assert "RS_SECTOR_UNAVAILABLE" in codes


def test_rs_split_keeps_point_sum_invariant():
    fundamentals, options, news = rich_inputs()
    snaps = {"SPY": {"perf20": 2.0}, "QQQ": {"perf20": 3.0}, "SMH": {"perf20": 4.0}}
    from veyraquant.models import MarketContext

    market = MarketContext("risk-on", 10.0, ["x"], [], snaps)
    contributions, _r, _k, evidence = score_components(
        "NVDA", full_snapshot(perf20=10.0), fundamentals, options, news, market
    )
    sums = defaultdict(float)
    for item in evidence:
        if item.points is not None:
            sums[item.component] += item.points
    for component, value in contributions.items():
        assert abs(sums[component] - value) < 1e-9


# --- R3.5: evidence metadata enrichment ---

def test_evidence_id_is_deterministic_and_timestamp_free():
    from veyraquant.evidence import EvidenceItem

    a = EvidenceItem("MOM_RSI_HEALTHY", "RSI healthy.", "reason", "momentum", 10, value=58.0)
    b = EvidenceItem("MOM_RSI_HEALTHY", "RSI healthy.", "reason", "momentum", 10, value=58.0,
                     timestamp="2026-07-13T00:00:00")
    c = EvidenceItem("MOM_RSI_HEALTHY", "RSI healthy.", "reason", "momentum", 10, value=61.0)
    assert a.evidence_id == b.evidence_id          # export time never enters the id
    assert a.evidence_id != c.evidence_id          # measured value does
    assert a.method == "deterministic_rule"
    assert a.confidence is None                    # numeric-or-None, not "rule"


def test_gates_carry_value_threshold_and_observed_at(monkeypatch):
    from veyraquant.models import FundamentalsData
    from veyraquant.signals import analyze_symbol
    from test_signal_consistency import (
        breakout_snapshot, bullish_market, dummy_daily, make_config, news_bundle, score_result,
    )

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _d: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _i: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *a, **k: score_result(72))

    result = analyze_symbol(
        "NVDA", dummy_daily(), None, FundamentalsData(days_to_earnings=1), None,
        news_bundle(0.0), bullish_market(), make_config(),
    )
    gate = next(item for item in result.evidence if item.code == "EARNINGS_BLACKOUT")
    assert gate.value == 1 and gate.threshold == 3  # measured vs rule boundary


def test_observed_at_uses_bar_time_not_export_time(monkeypatch):
    from veyraquant.models import FundamentalsData
    from veyraquant.signals import analyze_symbol
    from test_signal_consistency import bullish_market, dummy_daily, make_config, news_bundle

    daily = dummy_daily()
    result = analyze_symbol(
        "NVDA", daily, None, FundamentalsData(), None,
        news_bundle(0.5), bullish_market(), make_config(),
    )
    bar_iso = daily.index[-1].isoformat()
    technical = [i for i in result.evidence if i.source == "technical" and i.points]
    news_items = [i for i in result.evidence if i.source == "news"]
    assert technical and all(i.observed_at == bar_iso for i in technical)
    assert news_items and all(i.observed_at is None for i in news_items)


# --- R3.5.1: source-specific observed_at ---

def _analyze_with(fundamentals=None, options=None, news=None, daily=None, monkeypatch=None, symbol="NVDA", profile=None):
    from veyraquant.signals import analyze_symbol
    from test_signal_consistency import bullish_market, dummy_daily, make_config, news_bundle

    return analyze_symbol(
        symbol, dummy_daily() if daily is None else daily, None,
        fundamentals or FundamentalsData(), options,
        news or news_bundle(0.0), bullish_market(), make_config(), profile=profile,
    )


def test_options_evidence_uses_fetch_time_never_bar_time():
    opts = OptionsData("2026-08-21", 0.8, 1.5, 0.7, fetched_at="2026-07-12T01:02:03+00:00")
    result = _analyze_with(options=opts)
    option_items = [i for i in result.evidence if i.source == "options"]
    assert option_items
    assert all(i.observed_at == "2026-07-12T01:02:03+00:00" for i in option_items)

    stale = OptionsData("2026-08-21", 0.8, 1.5, 0.7)  # no fetched_at
    result = _analyze_with(options=stale)
    option_items = [i for i in result.evidence if i.source == "options"]
    assert option_items and all(i.observed_at is None for i in option_items)


def test_fundamental_evidence_uses_fetch_time_or_none():
    funda = FundamentalsData(recommendation_key="sell", fetched_at="2026-07-12T02:00:00+00:00")
    result = _analyze_with(fundamentals=funda)
    items = [i for i in result.evidence if i.source == "fundamental" and i.component != "gate"]
    assert items and all(i.observed_at == "2026-07-12T02:00:00+00:00" for i in items)

    legacy = FundamentalsData(recommendation_key="sell")  # legacy cache: no fetched_at
    result = _analyze_with(fundamentals=legacy)
    items = [i for i in result.evidence if i.source == "fundamental" and i.component != "gate"]
    assert items and all(i.observed_at is None for i in items)


def test_earnings_gate_observed_at_follows_fundamentals_fetch_time(monkeypatch):
    from test_signal_consistency import breakout_snapshot, score_result

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _d: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _i: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *a, **k: score_result(72))

    with_time = _analyze_with(
        fundamentals=FundamentalsData(days_to_earnings=1, fetched_at="2026-07-12T02:00:00+00:00")
    )
    gate = next(i for i in with_time.evidence if i.code == "EARNINGS_BLACKOUT")
    assert gate.observed_at == "2026-07-12T02:00:00+00:00"

    without_time = _analyze_with(fundamentals=FundamentalsData(days_to_earnings=1))
    gate = next(i for i in without_time.evidence if i.code == "EARNINGS_BLACKOUT")
    assert gate.observed_at is None


def test_liquidity_gate_keeps_daily_bar_time(monkeypatch):
    from dataclasses import replace
    from veyraquant.instruments import default_profile
    from test_signal_consistency import breakout_snapshot, dummy_daily, score_result

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _d: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _i: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *a, **k: score_result(72))

    thin = dummy_daily()
    thin["Volume"] = 100.0
    result = _analyze_with(daily=thin, profile=replace(default_profile("ZZZZ")))
    gate = next(i for i in result.evidence if i.code == "INSUFFICIENT_LIQUIDITY")
    assert gate.observed_at == thin.index[-1].isoformat()  # daily-derived gate


def test_market_evidence_has_no_borrowed_timestamp():
    result = _analyze_with()
    market_items = [i for i in result.evidence if i.source == "market" and i.component != "gate"]
    assert market_items
    assert all(i.observed_at is None for i in market_items)


def test_fundamentals_cache_roundtrips_fetched_at(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from veyraquant.data import DataClient
    from test_data import make_config as data_config

    client = DataClient(data_config(tmp_path))

    class LiveTicker:
        info = {"marketCap": 1};  calendar = None

    live = client.fetch_fundamentals("NVDA", LiveTicker(), [])
    assert live.fetched_at is not None

    # Cache read (ticker None) must report the ORIGINAL fetch time.
    cached = client.fetch_fundamentals("NVDA", None, [])
    assert cached.fetched_at == live.fetched_at

    # Legacy cache without _fetched_at -> None, no crash.
    legacy_path = client.cache_dir / "OLD_fundamentals.json"
    legacy_path.write_text('{"marketCap": 5}', encoding="utf-8")
    legacy = client.fetch_fundamentals("OLD", None, [])
    assert legacy.fetched_at is None and legacy.market_cap == 5
