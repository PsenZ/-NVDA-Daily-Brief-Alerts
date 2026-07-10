import math
from typing import Optional

import numpy as np

from .config import StrategyConfig
from .constants import MARKET_RISK_OFF, MARKET_RISK_ON
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
) -> tuple[dict[str, float], list[str], list[str]]:
    s = strategy or StrategyConfig()
    t = tech.values
    contributions: dict[str, float] = {}
    reasons: list[str] = []
    risks: list[str] = []

    trend = 0.0
    if t["sma5"] >= t["sma10"] >= t["sma20"]:
        trend += 10
        reasons.append("Short moving averages are stacked higher, supporting a trend-following bias.")
    if t["last"] > t["sma20"] > t["sma50"]:
        trend += 18
        reasons.append("Price remains above SMA20 and SMA50, keeping the intermediate trend constructive.")
    elif t["last"] > t["sma20"]:
        trend += 8
        reasons.append("Price still holds above SMA20, but trend strength needs more proof.")
    else:
        trend -= 8
        risks.append("Price has slipped back below SMA20 and trend persistence is weakening.")
    if not math.isnan(t["sma200"]) and t["last"] > t["sma200"]:
        trend += 8
        reasons.append("Price is still above SMA200, keeping the long-term structure supportive.")
    if t["last"] >= t["high_55"] * 0.98:
        trend += 6
        reasons.append("Price is trading near the 55-day high, which supports a trend continuation read.")
    contributions["trend"] = trend

    momentum = 0.0
    if t["macd"] > t["signal"] and t["macd_hist"] > t["macd_hist_prev"]:
        momentum += 12
        reasons.append("MACD is above signal and the histogram is expanding, showing improving momentum.")
    elif t["macd"] > t["signal"]:
        momentum += 6
    else:
        momentum -= 6
        risks.append("MACD has rolled under the signal line and momentum is softer.")
    if s.score_rsi_healthy_min <= t["rsi14"] <= s.score_rsi_healthy_max:
        momentum += 10
        reasons.append("RSI remains in a healthy range without obvious overheating.")
    elif t["rsi14"] > s.score_rsi_overheat:
        momentum -= 7
        risks.append("RSI is stretched and the reward for chasing is worse.")
    elif t["rsi14"] < s.score_rsi_weak:
        momentum -= 10
        risks.append("RSI is weak, showing limited demand support.")
    if t["adx14"] >= s.score_adx_trend_min and t["plus_di"] > t["minus_di"]:
        momentum += 10
        reasons.append("ADX is above 25 with +DI leading, which supports trend persistence.")
    contributions["momentum"] = momentum

    relative = 5.0
    spy_perf = _snapshot_perf(market, "SPY")
    qqq_perf = _snapshot_perf(market, "QQQ")
    benchmark_values = [value for value in (spy_perf, qqq_perf) if not math.isnan(value)]
    benchmark = float(np.mean(benchmark_values)) if benchmark_values else float("nan")
    if not math.isnan(t["perf20"]) and not math.isnan(benchmark):
        spread = t["perf20"] - benchmark
        relative += float(np.clip(spread, -10, 10))
        if spread >= 3:
            reasons.append(f"{symbol} is outperforming SPY/QQQ over the last 20 sessions.")
        elif spread <= -3:
            risks.append(f"{symbol} is lagging SPY/QQQ over the last 20 sessions.")
    contributions["relative_strength"] = relative

    volume = 0.0
    if t["vol_ratio_5"] >= s.score_vol_ratio_5_strong:
        volume += 12
        reasons.append("Volume is running above twice the 5-day average, which improves breakout confirmation.")
    elif t["vol_ratio"] >= s.score_vol_ratio_strong:
        volume += 10
        reasons.append("Volume is clearly above the 20-day average, supporting signal confirmation.")
    elif t["vol_ratio"] >= s.score_vol_ratio_moderate:
        volume += 5
        reasons.append("Volume is modestly above average.")
    elif t["vol_ratio_5"] < s.score_vol_ratio_light:
        volume += 4
        reasons.append("The pullback is happening on lighter 5-day volume, which fits a constructive retracement.")
    elif t["vol_ratio"] < s.score_vol_ratio_light:
        volume -= 4
        risks.append("Volume is below average and the breakout confirmation is weak.")
    contributions["volume"] = volume

    vol_opt = 5.0
    if t["atr_pct"] > 6:
        vol_opt -= 6
        risks.append("ATR as a percent of price is elevated, so position size should stay tighter.")
    if options and options.iv_mid is not None:
        if options.iv_mid >= 0.65:
            vol_opt -= 8
            risks.append("Implied volatility is elevated, pointing to heavier event risk.")
        elif options.iv_mid <= 0.4:
            vol_opt += 3
    if options and options.put_call_vol is not None:
        if options.put_call_vol >= 1.3:
            vol_opt -= 5
            risks.append("Put/Call volume is elevated and options sentiment is cautious.")
        elif options.put_call_vol <= 0.7:
            vol_opt += 4
            reasons.append("Put/Call volume is supportive of a more constructive bias.")
    contributions["volatility_options"] = vol_opt

    sentiment = 0.0
    social_score = news.social_sentiment.get("score", 0.0)
    if social_score >= social_sentiment_threshold:
        sentiment += 8
        reasons.append("Headline and social sentiment remain constructive.")
    elif social_score <= -social_sentiment_threshold:
        sentiment -= 8
        risks.append("Headline and social sentiment are leaning negative.")
    if news.news:
        sentiment += 2
    contributions["news_sentiment"] = sentiment

    discipline = 0.0
    if t["dist_ma5_pct"] > s.score_dist_ma5_extended_pct:
        discipline -= 8
        risks.append("Price is too extended above MA5 and chasing becomes harder to justify.")
    elif 0 <= t["dist_ma5_pct"] <= 2:
        discipline += 4
        reasons.append("Price is still close to MA5, keeping the entry rhythm healthier.")
    if abs(t["dist_ma10_pct"]) <= 2:
        discipline += 3
        reasons.append("Price is still close to MA10, which keeps the pullback support clearer.")
    contributions["discipline"] = discipline

    sector = 0.0
    smh_perf = _snapshot_perf(market, "SMH")
    qqq_perf = _snapshot_perf(market, "QQQ")
    if symbol in {"NVDA", "AMD", "MU", "SMH"} and not math.isnan(smh_perf) and smh_perf > 0:
        sector += 4
        reasons.append("SMH sector strength is supporting semiconductor follow-through.")
    if symbol in {"NVDA", "TSLA", "AAPL", "QQQ", "MSFT"} and not math.isnan(qqq_perf) and qqq_perf > 0:
        sector += 3
        reasons.append("QQQ remains constructive, which helps growth exposure.")
    contributions["sector_resonance"] = sector

    event_risk = 0.0
    recommendation = fundamentals.recommendation_key
    if recommendation in {"buy", "strong_buy"}:
        event_risk += 4
    elif recommendation in {"sell", "underperform"}:
        event_risk -= 8
        risks.append("Street expectations are not aligned with aggressive upside exposure.")
    if fundamentals.revenue_growth is not None and fundamentals.revenue_growth < 0:
        event_risk -= 4
        risks.append("Revenue growth is negative and the fundamental impulse needs more proof.")
    contributions["event_risk"] = event_risk

    market_score = float(np.clip(market.score, -15, 15))
    contributions["market_environment"] = market_score
    if market.label == MARKET_RISK_ON:
        reasons.append("The market filter remains in a risk-on state.")
    elif market.label == MARKET_RISK_OFF:
        risks.append("The market filter is in risk-off mode and reduces aggressive execution.")

    contributions["base"] = s.score_base
    return contributions, reasons, risks


def _snapshot_perf(market: MarketContext, symbol: str) -> float:
    snapshot = market.snapshots.get(symbol, {})
    value = snapshot.get("perf20")
    try:
        return float(value)
    except Exception:
        return float("nan")
