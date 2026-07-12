import math
from collections import defaultdict
from typing import Any

from .config import DEFAULT_SECTOR_MAP, DEFAULT_SECTOR_POSITION_LIMITS, DEFAULT_SECTOR_RISK_LIMITS
from .models import MarketContext, SignalResult
from .risk import budget_after, budget_exceeded
from .signals import refresh_signal_result
from .text_utils import dedupe


ACTIONABLE_ACTIONS = {"BUY_TRIGGER", "ADD_TRIGGER"}
CONVICTION_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def apply_portfolio_manager(
    results: list[SignalResult], market: MarketContext, config: Any | None = None
) -> tuple[list[SignalResult], list[str]]:
    notes: list[str] = []
    sector_map = _config_dict(config, "sector_map", DEFAULT_SECTOR_MAP)
    sector_risk_limits = _config_dict(config, "sector_risk_limits", DEFAULT_SECTOR_RISK_LIMITS)
    sector_position_limits = _config_dict(
        config, "sector_position_limits", DEFAULT_SECTOR_POSITION_LIMITS
    )
    market_bucket = _market_bucket(market)
    approved_limit = _approved_limit(config, market_bucket)
    heat_cap = _heat_cap(config)
    sector_risk_used: dict[str, float] = defaultdict(float)
    sector_position_used: dict[str, float] = defaultdict(float)
    heat_used = 0.0
    approved_count = 0

    for result in results:
        # Explicit sector_map wins; else the registry sector pre-filled by
        # analyze_symbol; else the general bucket.
        result.sector_bucket = (
            sector_map.get(result.symbol.upper()) or result.sector_bucket or "general"
        )
        result.approval_rank_score = _candidate_rank_score(result)
        result.approval_reason_code = ""
        result.defer_reason_code = ""
        result.sector_risk_after = 0.0
        result.sector_position_after = 0.0
        if result.action in ACTIONABLE_ACTIONS and result.is_actionable:
            result.portfolio_decision = "candidate"
            result.portfolio_reason = "Pending portfolio review."
        elif result.action == "REJECT":
            result.portfolio_decision = "rejected"
            result.portfolio_reason = "Blocked before portfolio approval."
        elif result.action == "RISK_REDUCE":
            result.portfolio_decision = "risk_action"
            result.portfolio_reason = "Risk control takes priority over new exposure."
        else:
            result.portfolio_decision = "watchlist"
            result.portfolio_reason = "Not ready for execution today."

    candidates = [item for item in results if item.portfolio_decision == "candidate"]
    # Deterministic priority: rank score desc, then daily rank, then symbol,
    # so shuffling the input order can never change the outcome.
    ordered = sorted(
        candidates,
        key=lambda item: (-_candidate_rank_score(item), item.rank, item.symbol),
    )

    for result in ordered:
        sector = result.sector_bucket
        if approved_count >= approved_limit:
            _defer(
                result,
                "capacity_deferred",
                "Deferred because the daily approval limit is already full.",
                notes,
                f"{result.symbol} deferred after reaching the daily approval limit ({approved_limit}).",
            )
            continue

        next_sector_risk = budget_after(sector_risk_used[sector], result.max_loss_pct)
        sector_risk_limit = _limit_for_sector(sector, sector_risk_limits)
        if budget_exceeded(sector_risk_used[sector], result.max_loss_pct, sector_risk_limit):
            _defer(
                result,
                "sector_risk_limit_exceeded",
                (
                    f"Deferred because {sector.replace('_', ' ')} risk would reach "
                    f"{next_sector_risk:.2f}% versus the {sector_risk_limit:.2f}% limit."
                ),
                notes,
                (
                    f"{result.symbol} deferred: {sector.replace('_', ' ')} risk budget "
                    f"{next_sector_risk:.2f}% exceeds {sector_risk_limit:.2f}%."
                ),
            )
            result.sector_risk_after = next_sector_risk
            result.sector_position_after = budget_after(
                sector_position_used[sector], result.position_pct
            )
            continue

        next_sector_position = budget_after(sector_position_used[sector], result.position_pct)
        sector_position_limit = _limit_for_sector(sector, sector_position_limits)
        if budget_exceeded(
            sector_position_used[sector], result.position_pct, sector_position_limit
        ):
            _defer(
                result,
                "sector_position_limit_exceeded",
                (
                    f"Deferred because {sector.replace('_', ' ')} position exposure would reach "
                    f"{next_sector_position:.2f}% versus the {sector_position_limit:.2f}% limit."
                ),
                notes,
                (
                    f"{result.symbol} deferred: {sector.replace('_', ' ')} position exposure "
                    f"{next_sector_position:.2f}% exceeds {sector_position_limit:.2f}%."
                ),
            )
            result.sector_risk_after = next_sector_risk
            result.sector_position_after = next_sector_position
            continue

        # Global portfolio heat is allocated HERE, after every approval
        # check has passed, so deferred candidates never consume it.
        heat_left = heat_cap - heat_used
        if heat_left <= 1e-9:
            _defer(
                result,
                "portfolio_heat_exhausted",
                "Deferred because the global portfolio heat budget is exhausted.",
                notes,
                f"{result.symbol} deferred: global portfolio heat budget exhausted.",
            )
            continue

        haircut_applied = False
        if result.max_loss_pct > heat_left + 1e-9:
            _haircut_for_heat(result, heat_left)
            haircut_applied = True
            notes.append(
                f"{result.symbol} trimmed to fit the remaining "
                f"{heat_left:.2f}% portfolio heat."
            )

        # Consume post-haircut actuals so budgets reflect what was granted.
        next_sector_risk = budget_after(sector_risk_used[sector], result.max_loss_pct)
        next_sector_position = budget_after(sector_position_used[sector], result.position_pct)

        result.portfolio_decision = "approved"
        if haircut_applied:
            result.approval_reason_code = "portfolio_heat_haircut"
        elif result.validation_warnings:
            result.approval_reason_code = "approved_with_validation_warning"
        else:
            result.approval_reason_code = "approved_clean"
        result.sector_risk_after = next_sector_risk
        result.sector_position_after = next_sector_position
        result.portfolio_reason = _approval_reason(result, sector)
        sector_risk_used[sector] = next_sector_risk
        sector_position_used[sector] = next_sector_position
        heat_used = budget_after(heat_used, result.max_loss_pct)
        approved_count += 1

    if market_bucket == "risk_off":
        notes.append(f"Risk-off market regime caps approved trades to {approved_limit}.")
    elif market_bucket == "neutral":
        notes.append(f"Neutral market regime caps approved trades to {approved_limit}.")
    if not candidates:
        notes.append("No actionable candidate reached portfolio review.")
    return results, dedupe(notes)


def _heat_cap(config: Any | None) -> float:
    try:
        return max(0.0, float(getattr(config, "portfolio_heat_max_pct")))
    except Exception:
        return 3.0


def _haircut_for_heat(result: SignalResult, heat_left: float) -> None:
    """Proportionally shrink the position so max loss fits the remaining
    global heat. Floor-rounded so approved heat can never exceed the cap."""
    ratio = heat_left / result.max_loss_pct
    new_loss = math.floor(heat_left * 100) / 100
    new_position = round(result.position_pct * ratio, 2)
    warning = "Portfolio heat is tight, so the suggested position has been trimmed."
    result.risks.append(warning)
    result.portfolio_warnings.append(warning)
    result.position_pct = new_position
    result.max_loss_pct = new_loss
    result.trade_plan.position_pct = new_position
    result.trade_plan.max_loss_pct = new_loss
    if result.trade_plan.account_equity is not None:
        result.trade_plan.position_value = (
            result.trade_plan.account_equity * new_position / 100
        )
    refresh_signal_result(result)


def _candidate_rank_score(result: SignalResult) -> float:
    validation_penalty = 6 if result.validation_warnings else 0
    heat_penalty = 4 if result.portfolio_warnings else 0
    return round(
        CONVICTION_WEIGHT.get(result.conviction_level, 1) * 25
        + result.score
        + min(max(result.raw_score - result.score, 0), 25)
        - validation_penalty
        - heat_penalty,
        2,
    )


def _approved_limit(config: Any | None, market_bucket: str) -> int:
    defaults = {"risk_on": 3, "neutral": 2, "risk_off": 0}
    attr = {
        "risk_on": "max_approved_actions_risk_on",
        "neutral": "max_approved_actions_neutral",
        "risk_off": "max_approved_actions_risk_off",
    }[market_bucket]
    try:
        return max(0, int(getattr(config, attr)))
    except Exception:
        return defaults[market_bucket]


def _market_bucket(market: MarketContext) -> str:
    if market.score < 0:
        return "risk_off"
    if market.score >= 10:
        return "risk_on"
    return "neutral"


def _limit_for_sector(sector: str, limits: dict[str, float]) -> float | None:
    if sector in limits:
        return limits[sector]
    return limits.get("general")


def _approval_reason(result: SignalResult, sector: str) -> str:
    if result.validation_warnings:
        return (
            f"Approved as a higher-conviction {sector.replace('_', ' ')} idea, "
            "but keep sizing disciplined because validation warnings remain."
        )
    return f"Approved as the best-ranked {sector.replace('_', ' ')} setup within risk budget."


def _defer(
    result: SignalResult,
    reason_code: str,
    reason: str,
    notes: list[str],
    note: str,
) -> None:
    result.portfolio_decision = "deferred"
    result.defer_reason_code = reason_code
    result.portfolio_reason = reason
    result.portfolio_warnings.append(reason)
    notes.append(note)


def _config_dict(config: Any | None, attr: str, default: dict) -> dict:
    value = getattr(config, attr, None)
    if isinstance(value, dict) and value:
        return dict(value)
    return dict(default)


