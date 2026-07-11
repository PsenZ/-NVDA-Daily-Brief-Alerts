from datetime import datetime, timedelta
from typing import Any, Callable

from .jsonl import read_entries, write_entries
from .models import SignalResult


BENCHMARK_SYMBOL = "SPY"
# Outcome horizons in trading days. 5 is the primary holding assumption;
# the others exist to test that assumption instead of hardcoding it.
HORIZONS = (1, 3, 5, 10)
HORIZON_RETRY_MAX_DAYS = 30


def sync_decision_log(
    path: str,
    now_dt: datetime,
    results: list[SignalResult],
    holding_days: int = 5,
    fetch_return: Callable[[str, str, int], float | None] | None = None,
) -> list[dict[str, Any]]:
    entries = read_entries(path)
    entries = _resolve_pending(entries, now_dt, holding_days, fetch_return or _fetch_holding_return)

    existing_ids = {entry["decision_id"] for entry in entries}
    for result in results:
        entry = _build_entry(now_dt, result, holding_days)
        if entry["decision_id"] not in existing_ids:
            entries.append(entry)
            existing_ids.add(entry["decision_id"])

    write_entries(path, entries)
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
        "raw_score": result.raw_score,
        "conviction_level": result.conviction_level,
        "decision_balance": result.decision_balance,
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
        "horizon_returns": {},
        "horizon_alphas": {},
    }


def _resolve_pending(
    entries: list[dict[str, Any]],
    now_dt: datetime,
    holding_days: int,
    fetch_return: Callable[[str, str, int], float | None],
) -> list[dict[str, Any]]:
    today = now_dt.date()
    cutoff = today - timedelta(days=holding_days)
    for entry in entries:
        status = entry.get("outcome_status")
        try:
            trade_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        except Exception:
            if status == "pending":
                entry["outcome_status"] = "unresolved"
            continue

        if status == "pending":
            if trade_date > cutoff:
                continue
            _fill_horizons(entry, fetch_return)
            primary_return = entry["horizon_returns"].get(str(holding_days))
            primary_alpha = entry["horizon_alphas"].get(str(holding_days))
            if primary_return is None and holding_days not in HORIZONS:
                symbol_return = fetch_return(entry["symbol"], entry["date"], holding_days)
                benchmark_return = fetch_return(BENCHMARK_SYMBOL, entry["date"], holding_days)
                if symbol_return is not None and benchmark_return is not None:
                    primary_return = round(symbol_return, 6)
                    primary_alpha = round(symbol_return - benchmark_return, 6)
            if primary_return is None or primary_alpha is None:
                entry["outcome_status"] = "unresolved"
                continue
            entry["five_day_return"] = primary_return
            entry["alpha_vs_spy"] = primary_alpha
            entry["outcome_status"] = "resolved"
        elif status == "resolved" and (today - trade_date).days <= HORIZON_RETRY_MAX_DAYS:
            # Longer horizons (e.g. 10d) are usually not observable yet when
            # the primary horizon resolves; keep backfilling them for a while.
            _fill_horizons(entry, fetch_return)
    return entries


def _fill_horizons(
    entry: dict[str, Any],
    fetch_return: Callable[[str, str, int], float | None],
) -> None:
    returns = entry.setdefault("horizon_returns", {})
    alphas = entry.setdefault("horizon_alphas", {})
    for horizon in HORIZONS:
        key = str(horizon)
        if returns.get(key) is not None and alphas.get(key) is not None:
            continue
        symbol_return = fetch_return(entry["symbol"], entry["date"], horizon)
        benchmark_return = fetch_return(BENCHMARK_SYMBOL, entry["date"], horizon)
        if symbol_return is None or benchmark_return is None:
            continue
        returns[key] = round(symbol_return, 6)
        alphas[key] = round(symbol_return - benchmark_return, 6)


def _fetch_holding_return(symbol: str, trade_date: str, holding_days: int) -> float | None:
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None

    try:
        start = datetime.strptime(trade_date, "%Y-%m-%d")
    except Exception:
        return None
    end = start + timedelta(days=holding_days * 2 + 10)
    history = yf.Ticker(symbol).history(start=trade_date, end=end.strftime("%Y-%m-%d"))
    # Strict horizon semantics: a "10-day return" must span 10 trading bars.
    # The old min() fallback silently relabeled a shorter window, which
    # would contaminate horizon statistics; not-enough-bars-yet -> None,
    # and the backfill loop retries on a later run.
    if len(history) <= holding_days:
        return None

    entry_price = float(history["Close"].iloc[0])
    exit_price = float(history["Close"].iloc[holding_days])
    if entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price
