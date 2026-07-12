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
)
from .evidence import gate_evidence
from .features import intraday_snapshot, tech_summary
from .instruments import InstrumentProfile, default_profile
from .models import (
    DataQuality,
    FundamentalsData,
    MarketContext,
    NewsBundle,
    OptionsData,
    SignalResult,
    TradePlan,
)
from .risk import portfolio_heat_cap
from .scoring import score_components
from .setups import apply_action_policy, choose_signal_type, classify_setup
from .text_utils import dedupe
from .trade_plan import _non_actionable_plan, build_trade_plan, preview_trade_plan
from .validator import validate_trade_plan


# Public surface. Several names are re-exported from submodules so that
# `from veyraquant.signals import ...` and tests that monkeypatch
# `veyraquant.signals.<name>` keep working after the module split.
__all__ = [
    "analyze_symbol",
    "assign_ranks",
    "enforce_portfolio_heat",
    "annotate_signal_result",
    "refresh_signal_result",
    "tech_summary",
    "intraday_snapshot",
    "score_components",
    "classify_setup",
    "apply_action_policy",
    "choose_signal_type",
    "build_trade_plan",
    "preview_trade_plan",
]


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
    profile: Optional[InstrumentProfile] = None,
) -> SignalResult:
    warnings = list(warnings or [])
    data_quality = data_quality or DataQuality()
    profile = profile or default_profile(symbol)
    min_bars = max(60, int(getattr(profile, "min_history_bars", 60) or 60))
    if daily is None or daily.empty or len(daily) < min_bars:
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
            evidence=[gate_evidence("insufficient_daily_data")],
        )
        return annotate_signal_result(result, market)

    tech = tech_summary(daily)
    intraday_data = intraday_snapshot(intraday)
    scored = score_components(
        symbol,
        tech,
        fundamentals,
        options,
        news,
        market,
        config.social_sentiment_threshold,
        getattr(config, "strategy", None),
        profile,
    )
    if len(scored) == 4:
        contributions, reasons, risks, evidence = scored
    else:  # test doubles may still return the legacy 3-tuple
        contributions, reasons, risks = scored
        evidence = []
    raw_score = sum(contributions.values())
    score = int(max(0, min(100, round(raw_score))))

    setup_type = classify_setup(tech, intraday_data, score, config)
    action, suppressed_by = apply_action_policy(setup_type, score, market, news, config)
    if action in ACTIONABLE_ACTIONS and not data_quality.actionable_allowed:
        risks.extend(data_quality.reasons[:3])
        suppressed_by.append("data_quality_gate")
        action = "WAIT"
    blackout_days = getattr(config, "earnings_blackout_days", 3)
    days_to_earnings = getattr(fundamentals, "days_to_earnings", None)
    if (
        action in ACTIONABLE_ACTIONS
        and days_to_earnings is not None
        and 0 <= days_to_earnings <= blackout_days
    ):
        risks.append(
            f"Earnings expected in {days_to_earnings} day(s); "
            "new entries are blocked inside the earnings blackout window."
        )
        suppressed_by.append("earnings_blackout")
        action = "WATCH"
    if action in ACTIONABLE_ACTIONS and (profile.is_leveraged or profile.is_inverse):
        risks.append(
            "Leveraged/inverse products break the swing-long assumptions "
            "(decay, path dependence); no fresh entries by policy."
        )
        suppressed_by.append("leveraged_product_policy")
        action = "WATCH"
    if action in ACTIONABLE_ACTIONS and profile.min_avg_dollar_volume:
        avg_dollar_volume = float(
            (daily["Close"] * daily["Volume"]).tail(20).mean()
        )
        if avg_dollar_volume < profile.min_avg_dollar_volume:
            risks.append(
                f"Average dollar volume ${avg_dollar_volume:,.0f} is below the "
                f"${profile.min_avg_dollar_volume:,.0f} liquidity floor."
            )
            suppressed_by.append("insufficient_liquidity")
            action = "WATCH"
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

    # Every suppression code becomes a machine-readable gate evidence item.
    evidence = list(evidence) + [gate_evidence(code) for code in suppressed_by]

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
        evidence=evidence,
    )
    result.sector_bucket = profile.sector or ""
    return annotate_signal_result(result, market)


def assign_ranks(results: list[SignalResult]) -> list[SignalResult]:
    sorted_results = sorted(results, key=lambda item: item.score, reverse=True)
    for idx, result in enumerate(sorted_results, start=1):
        result.rank = idx
    return sorted_results


def enforce_portfolio_heat(results: list[SignalResult], max_heat_pct: float) -> list[SignalResult]:
    """DEPRECATED (R3.5): no longer called by the production chain.

    Global heat is now allocated inside decision_manager.apply_portfolio_manager
    AFTER approval checks, so deferred candidates cannot consume it. This
    function is kept only as a compatibility API for external callers/tests;
    do not reintroduce it before apply_portfolio_manager - heat would then
    be charged twice.
    """
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
    evidence: Optional[list] = None,
) -> SignalResult:
    # Two-level fingerprint (R3.5): identity says WHAT the signal is;
    # material state says whether it changed in a way a human would care
    # about. Material fields are BANDED - exact prices, scores and text
    # never enter the hash, so intraday drift cannot bypass the cooldown,
    # while a score-band jump, regime flip or re-banded stop distance can.
    identity_input = f"{symbol}|{action}|{setup_type}"
    identity_hash = hashlib.sha1(identity_input.encode("utf-8")).hexdigest()[:12]
    material_input = "|".join(
        [
            identity_input,
            _score_band(score),
            market_regime,
            _entry_distance_band(plan, last_price),
            _stop_distance_band(plan),
            _rr_band(plan.rr),
        ]
    )
    material_state_hash = hashlib.sha1(material_input.encode("utf-8")).hexdigest()[:12]
    # Back-compat: signal_hash aliases the material hash; old state records
    # keyed on signal_hash keep working.
    signal_hash = material_state_hash
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
        identity_hash=identity_hash,
        material_state_hash=material_state_hash,
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
        evidence=evidence or [],
    )


def _score_band(score: int) -> str:
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    if score >= 50:
        return "50-59"
    return "0-49"


def _entry_distance_band(plan: TradePlan, last_price) -> str:
    if plan.entry_low is None or plan.entry_high is None or not last_price:
        return "na"
    mid = (float(plan.entry_low) + float(plan.entry_high)) / 2
    pct = (mid - float(last_price)) / float(last_price) * 100
    return f"{round(pct)}pct"  # 1% buckets


def _stop_distance_band(plan: TradePlan) -> str:
    if plan.stop_price is None or plan.entry_low is None or plan.entry_high is None:
        return "na"
    mid = (float(plan.entry_low) + float(plan.entry_high)) / 2
    if mid <= 0:
        return "na"
    pct = (mid - float(plan.stop_price)) / mid * 100
    return f"{round(pct * 2) / 2}pct"  # 0.5% buckets


def _rr_band(rr) -> str:
    try:
        value = float(rr)
    except Exception:
        return "na"
    if value <= 0:
        return "na"
    if value < 1.5:
        return "lt1.5"
    if value < 2.0:
        return "1.5-1.99"
    if value < 3.0:
        return "2.0-2.99"
    return "3plus"


def _derive_market_evidence(result: SignalResult, market: MarketContext) -> list[str]:
    evidence = dedupe(
        [item for item in result.reasons if any(marker in item for marker in MARKET_EVIDENCE_MARKERS)]
        + market.reasons[:2],
        drop_empty=True,
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
    candidates = dedupe(result.validation_warnings + result.rejection_reasons + result.risks, drop_empty=True)
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
