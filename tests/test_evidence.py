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
