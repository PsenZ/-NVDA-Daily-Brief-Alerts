"""Frozen trade plans armed by the nightly pipeline for intraday triggering.

The nightly run (completed daily bars only) decides and freezes the plan;
the intraday job only checks price levels against these frozen plans, so
intraday alerts are level-crossing events that cannot repaint.
"""
import json
import logging
import os
from datetime import date, timedelta
from typing import Any

from .models import SignalResult


logger = logging.getLogger(__name__)

STATE_VERSION = 1
ACTIVE_STATUS = "armed"
RESOLVED_KEEP_DAYS = 7


def load_plans(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return []
    except Exception:
        logger.warning("Failed to read armed plans: %s", path, exc_info=True)
        return []
    if not isinstance(payload, dict):
        return []
    plans = payload.get("plans", [])
    return [plan for plan in plans if isinstance(plan, dict)]


def save_plans(path: str, plans: list[dict[str, Any]]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {"version": STATE_VERSION, "plans": plans},
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def add_trading_days(start: date, trading_days: int) -> date:
    current = start
    remaining = max(0, trading_days)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def build_armed_plans(
    results: list[SignalResult], today: date, valid_days: int
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for result in results:
        if result.portfolio_decision != "approved" or not result.is_actionable:
            continue
        plan = result.trade_plan
        if plan.entry_low is None or plan.entry_high is None or plan.stop_price is None:
            continue
        plans.append(
            {
                "symbol": result.symbol,
                "plan_kind": result.plan_kind,
                "setup_type": result.setup_type,
                "score": result.score,
                "entry_low": round(float(plan.entry_low), 4),
                "entry_high": round(float(plan.entry_high), 4),
                "stop_price": round(float(plan.stop_price), 4),
                "target1": None if plan.target1 is None else round(float(plan.target1), 4),
                "target2": None if plan.target2 is None else round(float(plan.target2), 4),
                "position_pct": result.position_pct,
                "max_loss_pct": result.max_loss_pct,
                "created_date": today.isoformat(),
                "expires_date": add_trading_days(today, valid_days).isoformat(),
                "status": ACTIVE_STATUS,
                "triggered_at": None,
                "note": result.portfolio_reason,
            }
        )
    return plans


def merge_plans(
    existing: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    today: date,
) -> list[dict[str, Any]]:
    """New armed plans replace older armed plans for the same symbol.

    Resolved plans (triggered/invalidated/expired) are kept briefly for
    audit, then pruned after RESOLVED_KEEP_DAYS.
    """
    fresh_symbols = {plan["symbol"] for plan in fresh}
    kept: list[dict[str, Any]] = []
    for plan in existing:
        if plan.get("status") == ACTIVE_STATUS and plan.get("symbol") in fresh_symbols:
            continue
        if plan.get("status") != ACTIVE_STATUS:
            created = _parse_date(plan.get("created_date"))
            if created is not None and (today - created).days > RESOLVED_KEEP_DAYS:
                continue
        kept.append(plan)
    return kept + fresh


def expire_stale_plans(plans: list[dict[str, Any]], today: date) -> bool:
    changed = False
    for plan in plans:
        if plan.get("status") != ACTIVE_STATUS:
            continue
        expires = _parse_date(plan.get("expires_date"))
        if expires is not None and today > expires:
            plan["status"] = "expired"
            changed = True
    return changed


def active_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [plan for plan in plans if plan.get("status") == ACTIVE_STATUS]


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None
