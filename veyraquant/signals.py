import hashlib
from typing import Optional

import pandas as pd

from .config import AppConfig
from .constants import (
    ACTION_TO_ALERT_KIND,
    ACTION_TO_PLAN_KIND,
    ACTION_TO_RATING,
    ACTION_TO_SIGNAL_TYPE,
    ACTIONABLE_ACTIONS,
    MARKET_EVIDENCE_MARKERS,
    MARKET_RISK_OFF,
    MARKET_RISK_ON,
    SETUP_TO_ACTION,
)
from .features import intraday_snapshot, tech_summary
from .models import (
    DataQuality,
    FundamentalsData,
    MarketContext,
    NewsBundle,
    OptionsData,
    SignalResult,
    TechSnapshot,
    TradePlan,
)
from .risk import portfolio_heat_cap
from .scoring import _snapshot_perf, score_components
from .setups import apply_action_policy, choose_signal_type, classify_setup
from .trade_plan import build_trade_plan, preview_trade_plan
from .trade_plan import _non_actionable_plan
from .validator import validate_trade_plan


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
    data_quality: Optional[DataQuality] = None,
) -> SignalResult:
    warnings = list(warnings or [])
    data_quality = data_quality or DataQuality()
    if daily is None or daily.empty or len(daily) < 60:
        data_quality.data_quality_level = "LOW"
        data_quality.actionable_allowed = False
        data_quality.reasons.append("daily history is unavailable or too short")
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
            data_quality=data_quality,
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
    if action in ACTIONABLE_ACTIONS and not data_quality.actionable_allowed:
        risks.extend(data_quality.reasons[:3])
        suppressed_by.append("data_quality_gate")
        action = "WAIT"
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
        data_quality=data_quality,
    )
    return annotate_signal_result(result, market)


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
    data_quality: Optional[DataQuality] = None,
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
        data_quality=data_quality or DataQuality(),
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
    if result.data_quality.data_quality_level == "LOW":
        return "low"
    if result.action == "REJECT":
        return "low"
    if result.portfolio_warnings or len(result.validation_warnings) >= 2:
        return "low"
    if result.action in ACTIONABLE_ACTIONS and result.score >= 80 and not result.validation_warnings:
        if result.data_quality.data_quality_level == "MEDIUM":
            return "medium"
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
