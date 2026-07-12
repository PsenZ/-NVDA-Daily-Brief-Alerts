import math
from typing import Optional

import numpy as np

from .config import StrategyConfig
from .constants import MARKET_RISK_OFF, MARKET_RISK_ON
from .evidence import EvidenceCollector, EvidenceItem
from .instruments import InstrumentProfile, default_profile
from .models import FundamentalsData, MarketContext, NewsBundle, OptionsData, TechSnapshot


def score_components(
    symbol: str,
    tech: TechSnapshot,
    fundamentals: FundamentalsData,
    options: Optional[OptionsData],
    news: NewsBundle,
    market: MarketContext,
    social_sentiment_threshold: float = 0.15,
    strategy: Optional[StrategyConfig] = None,
    profile: Optional[InstrumentProfile] = None,
) -> tuple[dict[str, float], list[str], list[str], list[EvidenceItem]]:
    """Score a symbol; returns (contributions, reasons, risks, evidence).

    All narrative strings are routed through the EvidenceCollector so the
    reasons/risks lists stay byte-identical to the legacy output while
    every point carries a machine-readable evidence item. Invariant: per
    component, sum(evidence points) == contribution value.
    """
    s = strategy or StrategyConfig()
    profile = profile or default_profile(symbol)
    t = tech.values
    contributions: dict[str, float] = {}
    ev = EvidenceCollector()

    trend = 0.0
    if t["sma5"] >= t["sma10"] >= t["sma20"]:
        trend += 10
        ev.reason("TREND_MA_STACK", "Short moving averages are stacked higher, supporting a trend-following bias.", "trend", 10)
    if t["last"] > t["sma20"] > t["sma50"]:
        trend += 18
        ev.reason("TREND_ABOVE_SMA20_50", "Price remains above SMA20 and SMA50, keeping the intermediate trend constructive.", "trend", 18)
    elif t["last"] > t["sma20"]:
        trend += 8
        ev.reason("TREND_ABOVE_SMA20_ONLY", "Price still holds above SMA20, but trend strength needs more proof.", "trend", 8)
    else:
        trend -= 8
        ev.risk("TREND_BELOW_SMA20", "Price has slipped back below SMA20 and trend persistence is weakening.", "trend", -8)
    if not math.isnan(t["sma200"]) and t["last"] > t["sma200"]:
        trend += 8
        ev.reason("TREND_ABOVE_SMA200", "Price is still above SMA200, keeping the long-term structure supportive.", "trend", 8)
    if t["last"] >= t["high_55"] * 0.98:
        trend += 6
        ev.reason("TREND_NEAR_55D_HIGH", "Price is trading near the 55-day high, which supports a trend continuation read.", "trend", 6)
    contributions["trend"] = trend

    momentum = 0.0
    if t["macd"] > t["signal"] and t["macd_hist"] > t["macd_hist_prev"]:
        momentum += 12
        ev.reason("MOM_MACD_EXPANDING", "MACD is above signal and the histogram is expanding, showing improving momentum.", "momentum", 12)
    elif t["macd"] > t["signal"]:
        momentum += 6
        ev.info("MOM_MACD_ABOVE_SIGNAL", "MACD above signal without histogram expansion.", "momentum", 6)
    else:
        momentum -= 6
        ev.risk("MOM_MACD_BELOW_SIGNAL", "MACD has rolled under the signal line and momentum is softer.", "momentum", -6)
    if s.score_rsi_healthy_min <= t["rsi14"] <= s.score_rsi_healthy_max:
        momentum += 10
        ev.reason("MOM_RSI_HEALTHY", "RSI remains in a healthy range without obvious overheating.", "momentum", 10, value=round(t["rsi14"], 2))
    elif t["rsi14"] > s.score_rsi_overheat:
        momentum -= 7
        ev.risk("MOM_RSI_OVERHEATED", "RSI is stretched and the reward for chasing is worse.", "momentum", -7, value=round(t["rsi14"], 2))
    elif t["rsi14"] < s.score_rsi_weak:
        momentum -= 10
        ev.risk("MOM_RSI_WEAK", "RSI is weak, showing limited demand support.", "momentum", -10, value=round(t["rsi14"], 2))
    if t["adx14"] >= s.score_adx_trend_min and t["plus_di"] > t["minus_di"]:
        momentum += 10
        ev.reason("MOM_ADX_TREND", "ADX is above 25 with +DI leading, which supports trend persistence.", "momentum", 10, value=round(t["adx14"], 2))
    contributions["momentum"] = momentum

    # Relative strength is split (R3.5): broad market (vs SPY) and sector
    # (vs the instrument's own sector benchmark). The old behavior compared
    # against a SPY/QQQ average for every symbol and never actually
    # compared the stock to its sector - only whether the sector ETF rose.
    broad = 0.0
    spy_perf = _snapshot_perf(market, "SPY")
    if not math.isnan(t["perf20"]) and not math.isnan(spy_perf):
        broad_spread = t["perf20"] - spy_perf
        if broad_spread >= 3:
            broad += 6
            ev.reason("RS_BROAD_OUTPERFORM", f"{symbol} is outperforming SPY over the last 20 sessions.", "relative_strength_broad", 6, value=round(broad_spread, 2))
        elif broad_spread <= -3:
            broad -= 6
            ev.risk("RS_BROAD_LAG", f"{symbol} is lagging SPY over the last 20 sessions.", "relative_strength_broad", -6, value=round(broad_spread, 2))
        else:
            ev.info("RS_BROAD_NEUTRAL", "20-session performance is roughly in line with SPY.", "relative_strength_broad", 0.0, value=round(broad_spread, 2))
    contributions["relative_strength_broad"] = broad

    sector_rs = 0.0
    bench_symbol = profile.sector_benchmark
    if bench_symbol and bench_symbol != symbol:
        bench_perf20 = _snapshot_perf(market, bench_symbol)
        if math.isnan(t["perf20"]) or math.isnan(bench_perf20):
            # Never fabricate a neutral score from missing data.
            ev.info("RS_SECTOR_UNAVAILABLE", f"Sector benchmark {bench_symbol} data unavailable; no sector-relative scoring.", "relative_strength_sector", None, source="market")
        else:
            sector_spread = t["perf20"] - bench_perf20
            if sector_spread >= 3:
                sector_rs += 6
                ev.reason("RS_SECTOR_OUTPERFORM", f"{symbol} is leading its sector benchmark {bench_symbol} over the last 20 sessions.", "relative_strength_sector", 6, source="market", value=round(sector_spread, 2))
            elif sector_spread <= -3:
                sector_rs -= 6
                ev.risk("RS_SECTOR_LAG", f"{symbol} is lagging its sector benchmark {bench_symbol} over the last 20 sessions.", "relative_strength_sector", -6, source="market", value=round(sector_spread, 2))
            else:
                ev.info("RS_SECTOR_NEUTRAL", f"20-session performance is roughly in line with {bench_symbol}.", "relative_strength_sector", 0.0, source="market", value=round(sector_spread, 2))
    contributions["relative_strength_sector"] = sector_rs

    volume = 0.0
    if t["vol_ratio_5"] >= s.score_vol_ratio_5_strong:
        volume += 12
        ev.reason("VOL_SURGE_5D", "Volume is running above twice the 5-day average, which improves breakout confirmation.", "volume", 12, value=round(t["vol_ratio_5"], 2))
    elif t["vol_ratio"] >= s.score_vol_ratio_strong:
        volume += 10
        ev.reason("VOL_ABOVE_20D", "Volume is clearly above the 20-day average, supporting signal confirmation.", "volume", 10, value=round(t["vol_ratio"], 2))
    elif t["vol_ratio"] >= s.score_vol_ratio_moderate:
        volume += 5
        ev.reason("VOL_MODEST", "Volume is modestly above average.", "volume", 5, value=round(t["vol_ratio"], 2))
    elif t["vol_ratio_5"] < s.score_vol_ratio_light:
        volume += 4
        ev.reason("VOL_LIGHT_PULLBACK", "The pullback is happening on lighter 5-day volume, which fits a constructive retracement.", "volume", 4, value=round(t["vol_ratio_5"], 2))
    elif t["vol_ratio"] < s.score_vol_ratio_light:
        volume -= 4
        ev.risk("VOL_WEAK", "Volume is below average and the breakout confirmation is weak.", "volume", -4, value=round(t["vol_ratio"], 2))
    contributions["volume"] = volume

    vol_opt = 5.0
    ev.info("VOLOPT_BASELINE", "Volatility/options baseline.", "volatility_options", 5.0)
    if t["atr_pct"] > 6:
        vol_opt -= 6
        ev.risk("VOLOPT_ATR_ELEVATED", "ATR as a percent of price is elevated, so position size should stay tighter.", "volatility_options", -6, value=round(t["atr_pct"], 2))
    if options and options.iv_mid is not None:
        if options.iv_mid >= 0.65:
            vol_opt -= 8
            ev.risk("OPT_IV_HIGH", "Implied volatility is elevated, pointing to heavier event risk.", "volatility_options", -8, source="options", value=round(float(options.iv_mid), 3))
        elif options.iv_mid <= 0.4:
            vol_opt += 3
            ev.info("OPT_IV_LOW", "Implied volatility is subdued.", "volatility_options", 3, source="options", value=round(float(options.iv_mid), 3))
    if options and options.put_call_vol is not None:
        if options.put_call_vol >= 1.3:
            vol_opt -= 5
            ev.risk("OPT_PC_BEARISH", "Put/Call volume is elevated and options sentiment is cautious.", "volatility_options", -5, source="options", value=round(float(options.put_call_vol), 2))
        elif options.put_call_vol <= 0.7:
            vol_opt += 4
            ev.reason("OPT_PC_SUPPORTIVE", "Put/Call volume is supportive of a more constructive bias.", "volatility_options", 4, source="options", value=round(float(options.put_call_vol), 2))
    contributions["volatility_options"] = vol_opt

    sentiment = 0.0
    social_score = news.social_sentiment.get("score", 0.0)
    if social_score >= social_sentiment_threshold:
        sentiment += 8
        ev.reason("NEWS_SENT_POSITIVE", "Headline and social sentiment remain constructive.", "news_sentiment", 8, source="news", value=round(float(social_score), 3))
    elif social_score <= -social_sentiment_threshold:
        sentiment -= 8
        ev.risk("NEWS_SENT_NEGATIVE", "Headline and social sentiment are leaning negative.", "news_sentiment", -8, source="news", value=round(float(social_score), 3))
    if news.news:
        sentiment += 2
        ev.info("NEWS_COVERAGE", "Recent news coverage exists.", "news_sentiment", 2, source="news", value=len(news.news))
    contributions["news_sentiment"] = sentiment

    discipline = 0.0
    if t["dist_ma5_pct"] > s.score_dist_ma5_extended_pct:
        discipline -= 8
        ev.risk("DISC_EXTENDED_MA5", "Price is too extended above MA5 and chasing becomes harder to justify.", "discipline", -8, value=round(t["dist_ma5_pct"], 2))
    elif 0 <= t["dist_ma5_pct"] <= 2:
        discipline += 4
        ev.reason("DISC_NEAR_MA5", "Price is still close to MA5, keeping the entry rhythm healthier.", "discipline", 4, value=round(t["dist_ma5_pct"], 2))
    if abs(t["dist_ma10_pct"]) <= 2:
        discipline += 3
        ev.reason("DISC_NEAR_MA10", "Price is still close to MA10, which keeps the pullback support clearer.", "discipline", 3, value=round(t["dist_ma10_pct"], 2))
    contributions["discipline"] = discipline

    sector = 0.0
    if profile.sector_benchmark:
        bench_perf = _snapshot_perf(market, profile.sector_benchmark)
        if not math.isnan(bench_perf) and bench_perf > 0:
            sector += 4
            ev.reason("SECTOR_BENCH_STRONG", f"{profile.sector_benchmark} sector strength is supporting follow-through.", "sector_resonance", 4, source="market", value=round(bench_perf, 2))
    if profile.qqq_sensitive:
        qqq_sector_perf = _snapshot_perf(market, "QQQ")
        if not math.isnan(qqq_sector_perf) and qqq_sector_perf > 0:
            sector += 3
            ev.reason("SECTOR_QQQ_TAILWIND", "QQQ remains constructive, which helps growth exposure.", "sector_resonance", 3, source="market", value=round(qqq_sector_perf, 2))
    contributions["sector_resonance"] = sector

    event_risk = 0.0
    recommendation = fundamentals.recommendation_key
    if recommendation in {"buy", "strong_buy"}:
        event_risk += 4
        ev.info("FUND_RECO_BUY", "Street consensus leans buy.", "event_risk", 4, source="fundamental", value=str(recommendation))
    elif recommendation in {"sell", "underperform"}:
        event_risk -= 8
        ev.risk("FUND_RECO_SELL", "Street expectations are not aligned with aggressive upside exposure.", "event_risk", -8, source="fundamental", value=str(recommendation))
    if fundamentals.revenue_growth is not None and fundamentals.revenue_growth < 0:
        event_risk -= 4
        ev.risk("FUND_REVENUE_NEGATIVE", "Revenue growth is negative and the fundamental impulse needs more proof.", "event_risk", -4, source="fundamental", value=round(float(fundamentals.revenue_growth), 4))
    contributions["event_risk"] = event_risk

    market_score = float(np.clip(market.score, -15, 15))
    contributions["market_environment"] = market_score
    ev.info("MARKET_ENV_SCORE", "Market-environment score (clipped).", "market_environment", market_score, source="market", value=round(float(market.score), 2))
    if market.label == MARKET_RISK_ON:
        ev.reason("MARKET_RISK_ON_NOTE", "The market filter remains in a risk-on state.", "market_environment", None, source="market")
    elif market.label == MARKET_RISK_OFF:
        ev.risk("MARKET_RISK_OFF_NOTE", "The market filter is in risk-off mode and reduces aggressive execution.", "market_environment", None, source="market")

    contributions["base"] = s.score_base
    ev.info("BASE_SCORE", "Base score.", "base", s.score_base)
    return contributions, ev.reasons, ev.risks, ev.items


def _snapshot_perf(market: MarketContext, symbol: str) -> float:
    snapshot = market.snapshots.get(symbol, {})
    value = snapshot.get("perf20")
    try:
        return float(value)
    except Exception:
        return float("nan")
