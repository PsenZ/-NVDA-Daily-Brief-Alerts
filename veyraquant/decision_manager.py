from collections import defaultdict
from typing import Any

from .config import DEFAULT_SECTOR_MAP, DEFAULT_SECTOR_POSITION_LIMITS, DEFAULT_SECTOR_RISK_LIMITS
from .models import MarketContext, SignalResult
from .risk import budget_after, budget_exceeded
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
    sector_risk_used: dict[str, float] = defaultdict(float)
    sector_position_used: dict[str, float] = defaultdict(float)
    approved_count = 0

    for result in results:
        result.sector_bucket = _sector_for_symbol(result.symbol, sector_map)
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
    ordered = sorted(candidates, key=_candidate_priority, reverse=True)

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

        result.portfolio_decision = "approved"
        result.approval_reason_code = (
            "approved_clean" if not result.validation_warnings else "approved_with_validation_warning"
        )
        result.sector_risk_after = next_sector_risk
        result.sector_position_after = next_sector_position
        result.portfolio_reason = _approval_reason(result, sector)
        sector_risk_used[sector] = next_sector_risk
        sector_position_used[sector] = next_sector_position
        approved_count += 1

    if market_bucket == "risk_off":
        notes.append(f"Risk-off market regime caps approved trades to {approved_limit}.")
    elif market_bucket == "neutral":
        notes.append(f"Neutral market regime caps approved trades to {approved_limit}.")
    if not candidates:
        notes.append("No actionable candidate reached portfolio review.")
    return results, dedupe(notes)


def _candidate_priority(result: SignalResult) -> tuple[float, int]:
    rank_bonus = max(0, 100 - result.rank)
    return (_candidate_rank_score(result), rank_bonus)


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


def _sector_for_symbol(symbol: str, sector_map: dict[str, str]) -> str:
    return sector_map.get(symbol.upper(), "general")


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


