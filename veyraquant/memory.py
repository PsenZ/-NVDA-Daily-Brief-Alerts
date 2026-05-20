import json
import os
from datetime import datetime, timedelta
from typing import Any, Callable

from .models import SignalResult


BENCHMARK_SYMBOL = "SPY"


def sync_decision_log(
    path: str,
    now_dt: datetime,
    results: list[SignalResult],
    holding_days: int = 5,
    fetch_return: Callable[[str, str, int], float | None] | None = None,
) -> list[dict[str, Any]]:
    entries = _read_entries(path)
    entries = _resolve_pending(entries, now_dt, holding_days, fetch_return or _fetch_holding_return)

    existing_ids = {entry["decision_id"] for entry in entries}
    for result in results:
        entry = _build_entry(now_dt, result, holding_days)
        if entry["decision_id"] not in existing_ids:
            entries.append(entry)
            existing_ids.add(entry["decision_id"])

    _write_entries(path, entries)
    return entries


def _build_entry(now_dt: datetime, result: SignalResult, holding_days: int) -> dict[str, Any]:
    trade_date = now_dt.strftime("%Y-%m-%d")
    decision_id = f"{trade_date}|{result.symbol}|{result.signal_hash}"
    return {
        "decision_id": decision_id,
        "date": trade_date,
        "symbol": result.symbol,
        "setup_type": result.setup_type,
        "action": result.action,
        "rating": result.rating,
        "score": result.score,
        "bull_case": result.bull_case,
        "bear_case": result.bear_case,
        "market_regime": result.market_regime,
        "signal_hash": result.signal_hash,
        "trade_plan_summary": {
            "entry_zone": result.entry_zone,
            "stop": result.stop,
            "targets": result.targets,
            "position_pct": result.position_pct,
            "max_loss_pct": result.max_loss_pct,
        },
        "rejection_reasons": result.rejection_reasons,
        "portfolio_decision": result.portfolio_decision,
        "portfolio_reason": result.portfolio_reason,
        "outcome_status": "pending",
        "holding_days": holding_days,
        "five_day_return": None,
        "alpha_vs_spy": None,
    }


def _resolve_pending(
    entries: list[dict[str, Any]],
    now_dt: datetime,
    holding_days: int,
    fetch_return: Callable[[str, str, int], float | None],
) -> list[dict[str, Any]]:
    cutoff = now_dt.date() - timedelta(days=holding_days)
    for entry in entries:
        if entry.get("outcome_status") != "pending":
            continue
        try:
            trade_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        except Exception:
            entry["outcome_status"] = "unresolved"
            continue
        if trade_date > cutoff:
            continue

        symbol_return = fetch_return(entry["symbol"], entry["date"], holding_days)
        benchmark_return = fetch_return(BENCHMARK_SYMBOL, entry["date"], holding_days)
        if symbol_return is None or benchmark_return is None:
            entry["outcome_status"] = "unresolved"
            continue

        entry["five_day_return"] = round(symbol_return, 6)
        entry["alpha_vs_spy"] = round(symbol_return - benchmark_return, 6)
        entry["outcome_status"] = "resolved"
    return entries


def _fetch_holding_return(symbol: str, trade_date: str, holding_days: int) -> float | None:
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None

    try:
        start = datetime.strptime(trade_date, "%Y-%m-%d")
    except Exception:
        return None
    end = start + timedelta(days=holding_days + 10)
    history = yf.Ticker(symbol).history(start=trade_date, end=end.strftime("%Y-%m-%d"))
    if len(history) < 2:
        return None

    actual_idx = min(holding_days, len(history) - 1)
    entry_price = float(history["Close"].iloc[0])
    exit_price = float(history["Close"].iloc[actual_idx])
    if entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price


def _read_entries(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _write_entries(path: str, entries: list[dict[str, Any]]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
