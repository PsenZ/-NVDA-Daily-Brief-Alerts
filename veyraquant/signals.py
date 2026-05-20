import hashlib
import math
from typing import Optional

import numpy as np
import pandas as pd

from .config import AppConfig
from .indicators import adx, atr, bollinger_bands, macd, pct_change, rsi, volume_ratio
from .models import (
    FundamentalsData,
    MarketContext,
    NewsBundle,
    OptionsData,
    SignalResult,
    TechSnapshot,
    TradePlan,
)
from .risk import portfolio_heat_cap, position_size_pct
from .validator import validate_trade_plan


ACTIONABLE_ACTIONS = {"BUY_TRIGGER", "ADD_TRIGGER"}
ACTION_TO_SIGNAL_TYPE = {
    "BUY_TRIGGER": "\u7a81\u7834\u5165\u573a",
    "ADD_TRIGGER": "\u8d8b\u52bf\u56de\u8e29\u52a0\u4ed3",
    "WATCH": "\u6301\u6709\u89c2\u5bdf",
    "RISK_REDUCE": "\u51cf\u4ed3/\u98ce\u9669\u5347\u9ad8",
    "WAIT": "\u7981\u6b62\u4ea4\u6613/\u7b49\u5f85",
    "REJECT": "\u7981\u6b62\u4ea4\u6613/\u7b49\u5f85",
}
ACTION_TO_ALERT_KIND = {
    "BUY_TRIGGER": "breakout_entry",
    "ADD_TRIGGER": "pullback_add",
    "WATCH": "hold_watch",
    "RISK_REDUCE": "risk_reduce",
    "WAIT": "wait",
    "REJECT": "wait",
}
ACTION_TO_PLAN_KIND = {
    "BUY_TRIGGER": "buy",
    "ADD_TRIGGER": "add",
    "WATCH": "watch",
    "RISK_REDUCE": "reduce",
    "WAIT": "wait",
    "REJECT": "reject",
}
ACTION_TO_RATING = {
    "BUY_TRIGGER": "Buy",
    "ADD_TRIGGER": "Overweight",
    "WATCH": "Hold",
    "RISK_REDUCE": "Underweight",
    "WAIT": "Hold",
    "REJECT": "No Trade",
}
SETUP_TO_ACTION = {
    "breakout_entry": "BUY_TRIGGER",
    "pullback_add": "ADD_TRIGGER",
    "hold_watch": "WATCH",
    "risk_reduce": "RISK_REDUCE",
    "wait": "WAIT",
}
MARKET_RISK_OFF = "\u98ce\u9669\u89c4\u907f"
MARKET_RISK_ON = "\u98ce\u9669\u504f\u597d"
MARKET_EVIDENCE_MARKERS = ("market", "sector", "SPY", "QQQ", "SMH", "VIX", "relative strength")


def tech_summary(hist: pd.DataFrame) -> TechSnapshot:
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    chg = last - prev
    chg_pct = chg / prev * 100

    sma5_series = close.rolling(5).mean()
    sma10_series = close.rolling(10).mean()
    sma20_series = close.rolling(20).mean()
    sma50_series = close.rolling(50).mean()
    sma200_series = close.rolling(200).mean()
    rsi_series = rsi(close)
    macd_line, signal_line, hist_line = macd(close)
    bb_sma, bb_upper, bb_lower = bollinger_bands(close)
    atr14_series = atr(high, low, close)
    plus_di, minus_di, adx_series = adx(high, low, close)
    vol_ratio_series = volume_ratio(volume)
    vol_ratio_5_series = volume / (volume.rolling(5).mean() + 1e-9)
    daily_range = (high.iloc[-1] - low.iloc[-1]) + 1e-9

    values = {
        "last": last,
        "prev": prev,
        "chg": chg,
        "chg_pct": chg_pct,
        "sma5": float(sma5_series.iloc[-1]),
        "sma10": float(sma10_series.iloc[-1]),
        "sma20": float(sma20_series.iloc[-1]),
        "sma50": float(sma50_series.iloc[-1]),
        "sma200": float(sma200_series.iloc[-1]) if len(close) >= 200 else float("nan"),
        "sma5_prev": float(sma5_series.iloc[-2]),
        "sma10_prev": float(sma10_series.iloc[-2]),
        "sma20_prev": float(sma20_series.iloc[-2]),
        "sma50_prev": float(sma50_series.iloc[-2]),
        "rsi14": float(rsi_series.iloc[-1]),
        "rsi14_prev": float(rsi_series.iloc[-2]),
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "macd_hist": float(hist_line.iloc[-1]),
        "macd_hist_prev": float(hist_line.iloc[-2]),
        "high_20": float(close.rolling(20).max().iloc[-1]),
        "low_20": float(close.rolling(20).min().iloc[-1]),
        "high_55": float(close.rolling(55).max().iloc[-1]),
        "low_55": float(close.rolling(55).min().iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]),
        "bb_lower": float(bb_lower.iloc[-1]),
        "bb_sma": float(bb_sma.iloc[-1]),
        "bb_width": float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / (bb_sma.iloc[-1] + 1e-9)),
        "atr14": float(atr14_series.iloc[-1]),
        "atr_pct": float(atr14_series.iloc[-1] / (last + 1e-9) * 100),
        "plus_di": float(plus_di.iloc[-1]),
        "minus_di": float(minus_di.iloc[-1]),
        "adx14": float(adx_series.iloc[-1]),
        "vol_ratio": float(vol_ratio_series.iloc[-1]),
        "vol_ratio_5": float(vol_ratio_5_series.iloc[-1]),
        "perf20": pct_change(close, 20),
        "perf55": pct_change(close, 55),
        "close_position": float((last - low.iloc[-1]) / daily_range),
        "dist_ma5_pct": float((last - sma5_series.iloc[-1]) / (sma5_series.iloc[-1] + 1e-9) * 100),
        "dist_ma10_pct": float((last - sma10_series.iloc[-1]) / (sma10_series.iloc[-1] + 1e-9) * 100),
    }
    return TechSnapshot(values)


def intraday_snapshot(intraday: Optional[pd.DataFrame]) -> Optional[dict[str, float]]:
    if intraday is None or intraday.empty:
        return None
    close = intraday["Close"]
    volume = intraday["Volume"]
    latest = intraday.iloc[-1]
    prev = intraday.iloc[-2] if len(intraday) >= 2 else latest
    rolling_high = close.rolling(min(13, len(close))).max().iloc[-1]
    rolling_low = close.rolling(min(13, len(close))).min().iloc[-1]
    intraday_vol_ratio = volume.iloc[-1] / (volume.tail(min(20, len(volume))).mean() + 1e-9)
    return {
        "price": float(latest["Close"]),
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "prev_close": float(prev["Close"]),
        "chg_pct": float((latest["Close"] - prev["Close"]) / (prev["Close"] + 1e-9) * 100),
        "high_13": float(rolling_high),
        "low_13": float(rolling_low),
        "vol_ratio": float(intraday_vol_ratio),
    }


def analyze_symbol(
    symbol: str,
    daily: Optional[pd.DataFrame],
    intraday: Optional[pd.DataFrame],
    fundamentals: FundamentalsData,
    options: Optional[OptionsData],
    news: NewsBundle,
    market: MarketContext,
    config: AppConfig,
    warnings: Optional[list[str]] = None,
) -> SignalResult:
    warnings = list(warnings or [])
    if daily is None or daily.empty or len(daily) < 60:
        plan = _non_actionable_plan(
            plan_kind="wait",
            entry_zone="Waiting for cleaner data.",
            trigger="No trade until the daily history recovers.",
            cancel="Insufficient market history.",
        )
        result = _result(
            rank=0,
            symbol=symbol,
            setup_type="data_unavailable",
            signal_type=ACTION_TO_SIGNAL_TYPE["WAIT"],
            action="WAIT",
            is_actionable=False,
            suppressed_by=["insufficient_daily_data"],
            plan_kind="wait",
            score=0,
            market_regime=market.label,
            plan=plan,
            reasons=["Daily history is too short to support a reliable trade plan."],
            risks=warnings or ["Price history is unavailable."],
            contributions={},
            alert_kind="wait",
            last_price=None,
            warnings=warnings,
        )
        return annotate_signal_result(result, market)

    tech = tech_summary(daily)
    intraday_data = intraday_snapshot(intraday)
    contributions, reasons, risks = score_components(
        symbol, tech, fundamentals, options, news, market, config.social_sentiment_threshold
    )
    raw_score = sum(contributions.values())
    score = int(max(0, min(100, round(raw_score))))

    setup_type = classify_setup(tech, intraday_data, score, config)
    action, suppressed_by = apply_action_policy(setup_type, score, market, news, config)
    if action in ACTIONABLE_ACTIONS:
        preview_plan = preview_trade_plan(action, tech, config)
        if preview_plan.rr < config.min_rr and preview_plan.position_pct > 0:
            risks.append(
                f"RR {preview_plan.rr:.2f} is below the minimum requirement {config.min_rr:.2f}."
            )
            suppressed_by.append("rr_below_min")
            action = "WATCH"

    signal_type = ACTION_TO_SIGNAL_TYPE[action]
    alert_kind = ACTION_TO_ALERT_KIND[action]
    plan_kind = ACTION_TO_PLAN_KIND[action]
    is_actionable = action in ACTIONABLE_ACTIONS
    plan = build_trade_plan(action, tech, config)
    rejection_reasons: list[str] = []
    validation_warnings: list[str] = []
    if is_actionable:
        validation = validate_trade_plan(plan, config)
        if validation.warnings:
            validation_warnings = list(validation.warnings)
            risks.extend(validation.warnings)
        if not validation.is_valid:
            rejection_reasons = list(validation.errors)
            risks.extend(validation.errors)
            suppressed_by.append("trade_plan_validation_failed")
            action = "REJECT"
            signal_type = ACTION_TO_SIGNAL_TYPE[action]
            alert_kind = ACTION_TO_ALERT_KIND[action]
            plan_kind = ACTION_TO_PLAN_KIND[action]
            is_actionable = False
            plan = _non_actionable_plan(
                plan_kind="reject",
                entry_zone="Trade plan validation failed. No long entry is allowed.",
                trigger="Wait until the setup and plan parameters become valid again.",
                cancel="None.",
            )

    if warnings:
        risks.extend(warnings[:3])

    result = _result(
        rank=0,
        symbol=symbol,
        setup_type=setup_type,
        signal_type=signal_type,
        action=action,
        is_actionable=is_actionable,
        suppressed_by=suppressed_by,
        plan_kind=plan_kind,
        score=score,
        market_regime=market.label,
        plan=plan,
        reasons=reasons[:8],
        risks=risks[:8],
        contributions=contributions,
        alert_kind=alert_kind,
        last_price=tech.values["last"],
        raw_score=raw_score,
        warnings=warnings,
        rejection_reasons=rejection_reasons,
        validation_warnings=validation_warnings,
    )
    return annotate_signal_result(result, market)


def score_components(
    symbol: str,
    tech: TechSnapshot,
    fundamentals: FundamentalsData,
    options: Optional[OptionsData],
    news: NewsBundle,
    market: MarketContext,
    social_sentiment_threshold: float = 0.15,
) -> tuple[dict[str, float], list[str], list[str]]:
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
    if 45 <= t["rsi14"] <= 68:
        momentum += 10
        reasons.append("RSI remains in a healthy range without obvious overheating.")
    elif t["rsi14"] > 72:
        momentum -= 7
        risks.append("RSI is stretched and the reward for chasing is worse.")
    elif t["rsi14"] < 40:
        momentum -= 10
        risks.append("RSI is weak, showing limited demand support.")
    if t["adx14"] >= 25 and t["plus_di"] > t["minus_di"]:
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
    if t["vol_ratio_5"] >= 2.0:
        volume += 12
        reasons.append("Volume is running above twice the 5-day average, which improves breakout confirmation.")
    elif t["vol_ratio"] >= 1.5:
        volume += 10
        reasons.append("Volume is clearly above the 20-day average, supporting signal confirmation.")
    elif t["vol_ratio"] >= 1.1:
        volume += 5
        reasons.append("Volume is modestly above average.")
    elif t["vol_ratio_5"] < 0.7:
        volume += 4
        reasons.append("The pullback is happening on lighter 5-day volume, which fits a constructive retracement.")
    elif t["vol_ratio"] < 0.7:
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
    if t["dist_ma5_pct"] > 5:
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

    contributions["base"] = 35.0
    return contributions, reasons, risks


def choose_signal_type(
    tech: TechSnapshot,
    intraday: Optional[dict[str, float]],
    score: int,
    market: MarketContext,
    news: NewsBundle,
    config: AppConfig,
) -> tuple[str, str]:
    setup_type = classify_setup(tech, intraday, score, config)
    action, _suppressed = apply_action_policy(setup_type, score, market, news, config)
    if action in ACTIONABLE_ACTIONS:
        preview_plan = preview_trade_plan(action, tech, config)
        if preview_plan.rr < config.min_rr and preview_plan.position_pct > 0:
            action = "WATCH"
    return ACTION_TO_SIGNAL_TYPE[action], ACTION_TO_ALERT_KIND[action]


def classify_setup(
    tech: TechSnapshot,
    intraday: Optional[dict[str, float]],
    score: int,
    config: AppConfig,
) -> str:
    t = tech.values
    ma_stack = t["sma5"] >= t["sma10"] >= t["sma20"]
    breakout = (
        ma_stack
        and t["last"] >= t["high_20"] * 0.995
        and t["vol_ratio_5"] >= 2.0
        and t["close_position"] >= 0.7
        and t["dist_ma5_pct"] <= 5
    )
    pullback_ma5 = ma_stack and abs(t["dist_ma5_pct"]) <= 1.0
    pullback_ma10 = ma_stack and abs(t["dist_ma10_pct"]) <= 2.0
    pullback = (
        t["last"] > t["sma20"]
        and (pullback_ma5 or pullback_ma10)
        and t["vol_ratio_5"] <= 0.7
        and 42 <= t["rsi14"] <= 62
    )
    intraday_breakout = bool(
        intraday
        and intraday["price"] >= intraday["high_13"] * 0.998
        and intraday["vol_ratio"] >= 2.0
    )
    if score >= config.alert_score_threshold and (breakout or intraday_breakout):
        return "breakout_entry"
    if score >= config.alert_score_threshold - 5 and pullback:
        return "pullback_add"
    if score >= 55:
        return "hold_watch"
    if score <= 40 or t["rsi14"] > 74:
        return "risk_reduce"
    return "wait"


def apply_action_policy(
    setup_type: str,
    score: int,
    market: MarketContext,
    news: NewsBundle,
    config: AppConfig,
) -> tuple[str, list[str]]:
    action = SETUP_TO_ACTION[setup_type]
    suppressed_by: list[str] = []

    if action in ACTIONABLE_ACTIONS and market.label == MARKET_RISK_OFF and score < config.alert_score_threshold + 5:
        suppressed_by.append("market_risk_off")
        return "WAIT", suppressed_by

    negative_news = news.social_sentiment.get("score", 0.0) <= -max(
        config.social_sentiment_threshold, 0.2
    )
    if action in ACTIONABLE_ACTIONS and negative_news and score < config.alert_score_threshold + 10:
        suppressed_by.append("negative_news_veto")
        return "REJECT", suppressed_by

    return action, suppressed_by


def preview_trade_plan(action: str, tech: TechSnapshot, config: AppConfig) -> TradePlan:
    return _build_trade_plan(action, tech, config)


def build_trade_plan(action: str, tech: TechSnapshot, config: AppConfig) -> TradePlan:
    return _build_trade_plan(action, tech, config)


def _build_trade_plan(action: str, tech: TechSnapshot, config: AppConfig) -> TradePlan:
    t = tech.values
    last = t["last"]
    atr14 = max(t["atr14"], last * 0.01)

    if action == "BUY_TRIGGER":
        entry_low = last
        entry_high = last + 0.25 * atr14
        trigger = "Breakout closes near the 20-day high with intraday volume holding above 1.1x."
        cancel = "Close back below SMA20 or the market filter flips risk-off."
    elif action == "ADD_TRIGGER":
        entry_low = max(0.01, t["sma20"] - 0.25 * atr14)
        entry_high = t["sma20"] + 0.25 * atr14
        trigger = "Price stabilizes near SMA20 while RSI stays above 42."
        cancel = "Close below SMA20 with MACD histogram still weakening."
    elif action == "WATCH":
        return _non_actionable_plan(
            plan_kind="watch",
            entry_zone="Observation only. No fresh size yet.",
            trigger="Wait for a cleaner breakout or a healthier pullback reset.",
            cancel="Drop below key support or lose relative strength further.",
        )
    elif action == "RISK_REDUCE":
        return _non_actionable_plan(
            plan_kind="reduce",
            entry_zone="Risk management only.",
            trigger="Reduce exposure and avoid adding fresh size.",
            cancel="Trend repairs and conviction improves again.",
        )
    elif action == "REJECT":
        return _non_actionable_plan(
            plan_kind="reject",
            entry_zone="Rejected. No executable long plan.",
            trigger="Reassess after the blocking condition clears.",
            cancel="None.",
        )
    else:
        return _non_actionable_plan(
            plan_kind="wait",
            entry_zone="Wait for a cleaner trend and stronger confirmation.",
            trigger="Wait for the setup, market, and volume confirmation to align.",
            cancel="None.",
        )

    entry_mid = (entry_low + entry_high) / 2
    stop = max(0.01, entry_mid - config.atr_stop_multiplier * atr14)
    risk_per_share = entry_mid - stop
    target1 = entry_mid + config.min_rr * risk_per_share
    target2 = entry_mid + max(config.min_rr + 1.0, 2.5) * risk_per_share
    rr = (target1 - entry_mid) / (risk_per_share + 1e-9)

    sizing = position_size_pct(
        entry_mid,
        stop,
        config.risk_per_trade_pct,
        config.max_position_pct,
        config.account_equity,
    )

    return TradePlan(
        entry_zone=f"${entry_low:.2f} - ${entry_high:.2f}",
        stop=f"${stop:.2f}",
        targets=f"${target1:.2f} / ${target2:.2f}",
        position_pct=sizing.position_pct,
        max_loss_pct=sizing.max_loss_pct,
        rr=round(rr, 2),
        trigger=trigger,
        cancel=cancel,
        account_equity=config.account_equity,
        position_value=sizing.position_value,
    )


def assign_ranks(results: list[SignalResult]) -> list[SignalResult]:
    sorted_results = sorted(results, key=lambda item: item.score, reverse=True)
    for idx, result in enumerate(sorted_results, start=1):
        result.rank = idx
    return sorted_results


def enforce_portfolio_heat(results: list[SignalResult], max_heat_pct: float) -> list[SignalResult]:
    heat_left = max_heat_pct
    for result in results:
        if not result.is_actionable:
            continue
        if result.max_loss_pct <= 0 or result.position_pct <= 0:
            continue
        new_position, new_loss = portfolio_heat_cap(
            result.position_pct, result.max_loss_pct, max(0.0, heat_left)
        )
        if new_loss < result.max_loss_pct:
            warning = "Portfolio heat is tight, so the suggested position has been trimmed."
            result.risks.append(warning)
            result.portfolio_warnings.append(warning)
            result.position_pct = new_position
            result.max_loss_pct = new_loss
            result.trade_plan.position_pct = new_position
            result.trade_plan.max_loss_pct = new_loss
            if result.trade_plan.account_equity is not None:
                result.trade_plan.position_value = result.trade_plan.account_equity * new_position / 100
            refresh_signal_result(result)
        heat_left -= result.max_loss_pct
    return results


def annotate_signal_result(result: SignalResult, market: MarketContext) -> SignalResult:
    result.rating = ACTION_TO_RATING.get(result.action, "Hold")
    result.market_evidence = _derive_market_evidence(result, market)
    result.bull_case = _derive_bull_case(result)
    result.bear_case = _derive_bear_case(result)
    refresh_signal_result(result)
    return result


def refresh_signal_result(result: SignalResult) -> SignalResult:
    result.conviction_level = _conviction_level(result)
    result.decision_balance = _decision_balance(result)
    return result


def _snapshot_perf(market: MarketContext, symbol: str) -> float:
    snapshot = market.snapshots.get(symbol, {})
    value = snapshot.get("perf20")
    try:
        return float(value)
    except Exception:
        return float("nan")


def _result(
    rank: int,
    symbol: str,
    setup_type: str,
    signal_type: str,
    action: str,
    is_actionable: bool,
    suppressed_by: list[str],
    plan_kind: str,
    score: int,
    market_regime: str,
    plan: TradePlan,
    reasons: list[str],
    risks: list[str],
    contributions: dict[str, float],
    alert_kind: str,
    last_price: Optional[float],
    raw_score: float = 0.0,
    warnings: Optional[list[str]] = None,
    rejection_reasons: Optional[list[str]] = None,
    validation_warnings: Optional[list[str]] = None,
) -> SignalResult:
    hash_input = f"{symbol}|{action}|{score}|{plan.entry_zone}|{plan.stop}|{plan.targets}"
    signal_hash = hashlib.sha1(hash_input.encode("utf-8")).hexdigest()[:12]
    return SignalResult(
        rank=rank,
        symbol=symbol,
        signal_type=signal_type,
        score=score,
        market_regime=market_regime,
        entry_zone=plan.entry_zone,
        stop=plan.stop,
        targets=plan.targets,
        position_pct=plan.position_pct,
        max_loss_pct=plan.max_loss_pct,
        reasons=reasons,
        risks=risks,
        contributions=contributions,
        trade_plan=plan,
        alert_kind=alert_kind,
        signal_hash=signal_hash,
        last_price=last_price,
        raw_score=raw_score,
        warnings=warnings or [],
        rejection_reasons=rejection_reasons or [],
        setup_type=setup_type,
        action=action,
        is_actionable=is_actionable,
        suppressed_by=suppressed_by,
        plan_kind=plan_kind,
        validation_warnings=validation_warnings or [],
    )


def _non_actionable_plan(plan_kind: str, entry_zone: str, trigger: str, cancel: str) -> TradePlan:
    return TradePlan(
        entry_zone=entry_zone,
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        rr=0.0,
        trigger=trigger,
        cancel=cancel,
        account_equity=None,
        position_value=None,
    )


def _derive_market_evidence(result: SignalResult, market: MarketContext) -> list[str]:
    evidence = _top_unique(
        [item for item in result.reasons if any(marker in item for marker in MARKET_EVIDENCE_MARKERS)]
        + market.reasons[:2]
    )
    if evidence:
        return evidence[:2]
    return [f"Market regime is {market.label} with score {market.score:+.1f}."]


def _derive_bull_case(result: SignalResult) -> list[str]:
    if result.action == "RISK_REDUCE":
        return []
    candidates = list(result.reasons)
    if result.action in ACTIONABLE_ACTIONS:
        candidates = candidates[:2]
    else:
        candidates = candidates[:1]
    if candidates:
        return candidates
    if result.action in ACTIONABLE_ACTIONS:
        return ["Enough aligned evidence remains for an actionable setup."]
    return ["No strong upside edge is ready for fresh execution."]


def _derive_bear_case(result: SignalResult) -> list[str]:
    candidates = _top_unique(result.validation_warnings + result.rejection_reasons + result.risks)
    if candidates:
        return candidates[:2]
    if result.action == "BUY_TRIGGER":
        return ["The breakout still needs to hold after entry."]
    if result.action == "ADD_TRIGGER":
        return ["The pullback can fail if support breaks too quickly."]
    if result.action == "RISK_REDUCE":
        return ["Risk control takes priority while trend durability is weaker."]
    return ["No clean execution edge is available right now."]


def _conviction_level(result: SignalResult) -> str:
    if result.action == "REJECT":
        return "low"
    if result.portfolio_warnings or len(result.validation_warnings) >= 2:
        return "low"
    if result.action in ACTIONABLE_ACTIONS and result.score >= 80 and not result.validation_warnings:
        return "high"
    if result.action in ACTIONABLE_ACTIONS and result.score >= 65:
        return "medium"
    if result.action == "RISK_REDUCE":
        return "medium"
    return "low"


def _decision_balance(result: SignalResult) -> str:
    if result.action == "REJECT":
        return "blocked"
    if result.action == "RISK_REDUCE":
        return "defensive"
    if result.action in ACTIONABLE_ACTIONS and result.validation_warnings:
        return "fragile"
    if result.action in ACTIONABLE_ACTIONS and result.bear_case:
        return "mixed"
    if result.action in ACTIONABLE_ACTIONS:
        return "favorable"
    return "mixed"


def _top_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
