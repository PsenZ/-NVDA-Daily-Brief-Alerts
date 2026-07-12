"""Static JSON export feeding the docs/ dashboard.

The nightly pipeline writes docs/data/briefs/YYYY-MM-DD.json plus a
latest.json copy, an index of available dates, a decisions.json mirror
of the decision log, and an armed_plans.json mirror. GitHub Pages serves
docs/ as-is; the frontend only ever fetches these files. Export failures
are logged and swallowed - the email pipeline must never die for the
dashboard's sake.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from .jsonl import read_entries
from .models import MarketContext, SignalResult
from .reporting import _trading_posture, format_dual_time


logger = logging.getLogger(__name__)

# v2: results[].evidence (structured, timestamped evidence trail).
SCHEMA_VERSION = 2


def build_brief_payload(
    results: list[SignalResult],
    market: MarketContext,
    config: Any,
    now_dt: datetime,
    portfolio_notes: Optional[list[str]] = None,
    review_notes: Optional[list[str]] = None,
    sample: bool = False,
) -> dict[str, Any]:
    approved = [r for r in results if r.portfolio_decision == "approved"]
    deferred = [
        r
        for r in results
        if r.portfolio_decision == "deferred" and r.action not in {"RISK_REDUCE", "REJECT"}
    ]
    watchlist = [
        r
        for r in results
        if r.portfolio_decision == "watchlist" and r.action in {"WATCH", "WAIT"}
    ]
    risk_actions = [r for r in results if r.action == "RISK_REDUCE"]
    rejected = [r for r in results if r.action == "REJECT"]
    return {
        "schema_version": SCHEMA_VERSION,
        "sample": sample,
        "date": now_dt.strftime("%Y-%m-%d"),
        "generated_at": now_dt.isoformat(),
        "dual_time": format_dual_time(now_dt),
        "meta": {
            "symbols": list(getattr(config, "symbols", [])),
            "market_symbols": list(getattr(config, "market_symbols", [])),
        },
        "market": {
            "label": market.label,
            "score": float(market.score),
            "reasons": list(market.reasons),
            "risks": list(market.risks),
            "snapshots": {
                symbol: {k: _num(v) for k, v in (snapshot or {}).items()}
                for symbol, snapshot in market.snapshots.items()
            },
        },
        "summary": {
            "trading_posture": _trading_posture(market, len(approved)),
            "approved": len(approved),
            "deferred": len(deferred),
            "watchlist": len(watchlist),
            "risk_actions": len(risk_actions),
            "rejected": len(rejected),
        },
        "results": [_result_payload(r, now_dt.isoformat()) for r in results],
        "portfolio_notes": list(portfolio_notes or []),
        "review_notes": list(review_notes or []),
    }


def export_dashboard(
    results: list[SignalResult],
    market: MarketContext,
    config: Any,
    now_dt: datetime,
    portfolio_notes: Optional[list[str]] = None,
    review_notes: Optional[list[str]] = None,
) -> None:
    """Best-effort export of everything the dashboard reads."""
    export_dir = getattr(config, "export_dir", "")
    if not export_dir:
        return
    try:
        payload = build_brief_payload(
            results, market, config, now_dt, portfolio_notes, review_notes
        )
        export_daily_brief(export_dir, payload)
        export_decisions(export_dir, getattr(config, "memory_log_path", ""))
        logger.info("Dashboard export written to %s", export_dir)
    except Exception:
        logger.warning("Dashboard export failed; email pipeline unaffected.", exc_info=True)


def export_daily_brief(export_dir: str, payload: dict[str, Any]) -> None:
    date = payload["date"]
    _write_json(os.path.join(export_dir, "briefs", f"{date}.json"), payload)
    _write_json(os.path.join(export_dir, "latest.json"), payload)
    index_path = os.path.join(export_dir, "index.json")
    dates: list[str] = []
    try:
        with open(index_path, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
        if isinstance(existing, dict):
            dates = [str(item) for item in existing.get("dates", [])]
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("Unreadable brief index; rebuilding.", exc_info=True)
    if date not in dates:
        dates.append(date)
    _write_json(index_path, {"dates": sorted(dates)})


def export_decisions(export_dir: str, memory_log_path: str) -> None:
    if not memory_log_path:
        return
    entries = read_entries(memory_log_path)
    _write_json(os.path.join(export_dir, "decisions.json"), {"entries": entries})


def export_armed_plans(export_dir: str, plans: list[dict[str, Any]]) -> None:
    _write_json(os.path.join(export_dir, "armed_plans.json"), {"plans": plans})


def _result_payload(result: SignalResult, generated_at: str = "") -> dict[str, Any]:
    plan = result.trade_plan
    evidence_payload = []
    for item in getattr(result, "evidence", []) or []:
        if hasattr(item, "to_dict"):
            entry = item.to_dict()
        elif isinstance(item, dict):
            entry = dict(item)
        else:
            continue
        entry["timestamp"] = entry.get("timestamp") or generated_at
        evidence_payload.append(entry)
    return {
        "evidence": evidence_payload,
        "symbol": result.symbol,
        "rank": result.rank,
        "score": int(result.score),
        "raw_score": _num(result.raw_score),
        "action": result.action,
        "setup_type": result.setup_type,
        "signal_type": result.signal_type,
        "rating": result.rating,
        "conviction_level": result.conviction_level,
        "decision_balance": result.decision_balance,
        "is_actionable": bool(result.is_actionable),
        "portfolio_decision": result.portfolio_decision,
        "portfolio_reason": result.portfolio_reason,
        "suppressed_by": list(result.suppressed_by),
        "last_price": _num(result.last_price),
        "data_quality_level": result.data_quality.data_quality_level,
        "contributions": {key: _num(value) for key, value in result.contributions.items()},
        "reasons": list(result.reasons),
        "risks": list(result.risks),
        "bull_case": list(result.bull_case),
        "bear_case": list(result.bear_case),
        "market_evidence": list(result.market_evidence),
        "validation_warnings": list(result.validation_warnings),
        "position_context": getattr(result, "position_context", ""),
        "suggested_posture": getattr(result, "suggested_posture", ""),
        "plan": {
            "entry_zone": plan.entry_zone,
            "stop": plan.stop,
            "targets": plan.targets,
            "entry_low": _num(plan.entry_low),
            "entry_high": _num(plan.entry_high),
            "stop_price": _num(plan.stop_price),
            "target1": _num(plan.target1),
            "target2": _num(plan.target2),
            "rr": _num(plan.rr),
            "position_pct": _num(result.position_pct),
            "max_loss_pct": _num(result.max_loss_pct),
            "trigger": plan.trigger,
            "cancel": plan.cancel,
        },
    }


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 6)


def _write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=True)
