from typing import Optional

from .config import AppConfig
from .constants import (
    ACTION_TO_ALERT_KIND,
    ACTION_TO_SIGNAL_TYPE,
    ACTIONABLE_ACTIONS,
    MARKET_RISK_OFF,
    SETUP_TO_ACTION,
)
from .models import MarketContext, NewsBundle, TechSnapshot
from .trade_plan import preview_trade_plan


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
    strategy = getattr(config, "strategy", None)
    breakout_score_min = config.alert_score_threshold + getattr(strategy, "breakout_score_offset", 0)
    pullback_score_min = config.alert_score_threshold + getattr(strategy, "pullback_score_offset", -5)
    ma_stack = t["sma5"] >= t["sma10"] >= t["sma20"]
    breakout = (
        ma_stack
        and t["last"] >= t["high_20"] * getattr(strategy, "breakout_high20_ratio", 0.995)
        and t["vol_ratio_5"] >= getattr(strategy, "breakout_vol_ratio_5_min", 2.0)
        and t["close_position"] >= getattr(strategy, "breakout_close_position_min", 0.7)
        and t["dist_ma5_pct"] <= getattr(strategy, "breakout_max_dist_ma5_pct", 5.0)
    )
    pullback_ma5 = ma_stack and abs(t["dist_ma5_pct"]) <= getattr(strategy, "pullback_ma5_distance_pct", 1.0)
    pullback_ma10 = ma_stack and abs(t["dist_ma10_pct"]) <= getattr(strategy, "pullback_ma10_distance_pct", 2.0)
    pullback = (
        t["last"] > t["sma20"]
        and (pullback_ma5 or pullback_ma10)
        and t["vol_ratio_5"] <= getattr(strategy, "pullback_vol_ratio_5_max", 0.7)
        and getattr(strategy, "pullback_rsi_min", 42.0) <= t["rsi14"] <= getattr(strategy, "pullback_rsi_max", 62.0)
    )
    intraday_breakout = bool(
        intraday
        and intraday["price"] >= intraday["high_13"] * getattr(strategy, "intraday_breakout_high13_ratio", 0.998)
        and intraday["vol_ratio"] >= getattr(strategy, "intraday_breakout_vol_ratio_min", 2.0)
    )
    if score >= breakout_score_min and (breakout or intraday_breakout):
        return "breakout_entry"
    if score >= pullback_score_min and pullback:
        return "pullback_add"
    if score >= getattr(strategy, "hold_watch_score_min", 55):
        return "hold_watch"
    if score <= getattr(strategy, "risk_reduce_score_max", 40) or t["rsi14"] > getattr(strategy, "risk_reduce_rsi_overheat", 74.0):
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
