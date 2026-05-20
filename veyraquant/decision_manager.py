from collections import defaultdict

from .models import MarketContext, SignalResult


ACTIONABLE_ACTIONS = {"BUY_TRIGGER", "ADD_TRIGGER"}
SECTOR_MAP = {
    "NVDA": "semiconductor",
    "AMD": "semiconductor",
    "MU": "semiconductor",
    "SMH": "semiconductor",
    "QQQ": "mega_growth",
    "AAPL": "mega_growth",
    "MSFT": "mega_growth",
    "TSLA": "auto_growth",
}
CONVICTION_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def apply_portfolio_manager(
    results: list[SignalResult], market: MarketContext
) -> tuple[list[SignalResult], list[str]]:
    notes: list[str] = []
    approved_limit = _approved_limit(market.label)
    sector_limit = 2 if market.label == "风险偏好" else 1
    sector_counts: dict[str, int] = defaultdict(int)
    approved_count = 0

    for result in results:
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
        sector = _sector_for_symbol(result.symbol)
        if approved_count >= approved_limit:
            result.portfolio_decision = "deferred"
            result.portfolio_reason = "Deferred because the daily approval limit is already full."
            notes.append(
                f"{result.symbol} deferred after reaching the daily approval limit ({approved_limit})."
            )
            continue
        if sector_counts[sector] >= sector_limit:
            result.portfolio_decision = "deferred"
            result.portfolio_reason = (
                f"Deferred to avoid concentration in the {sector.replace('_', ' ')} bucket."
            )
            notes.append(
                f"{result.symbol} deferred due to {sector.replace('_', ' ')} concentration."
            )
            continue

        result.portfolio_decision = "approved"
        result.portfolio_reason = _approval_reason(result, sector)
        approved_count += 1
        sector_counts[sector] += 1

    if market.label == "风险规避":
        notes.append("Risk-off market regime caps approved trades to one.")
    elif market.label != "风险偏好":
        notes.append("Neutral market regime keeps approvals selective.")
    if not candidates:
        notes.append("No actionable candidate reached portfolio review.")
    return results, _dedupe_preserve_order(notes)


def _candidate_priority(result: SignalResult) -> tuple[int, int, int, int]:
    validation_penalty = 0 if not result.validation_warnings else -1
    clean_heat = 0 if not result.portfolio_warnings else -1
    rank_bonus = max(0, 100 - result.rank)
    return (
        CONVICTION_WEIGHT.get(result.conviction_level, 1),
        validation_penalty,
        clean_heat,
        result.score + rank_bonus,
    )


def _approved_limit(market_label: str) -> int:
    if market_label == "风险规避":
        return 1
    if market_label == "风险偏好":
        return 3
    return 2


def _sector_for_symbol(symbol: str) -> str:
    return SECTOR_MAP.get(symbol.upper(), "general")


def _approval_reason(result: SignalResult, sector: str) -> str:
    if result.validation_warnings:
        return (
            f"Approved as a higher-conviction {sector.replace('_', ' ')} idea, "
            "but keep sizing disciplined because validation warnings remain."
        )
    return f"Approved as the best-ranked {sector.replace('_', ' ')} setup on today's board."


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
