from .config import AppConfig
from .models import TechSnapshot, TradePlan
from .risk import position_size_pct


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
        entry_low=entry_low,
        entry_high=entry_high,
        stop_price=stop,
        target1=target1,
        target2=target2,
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
