"""Intraday level-crossing checks against frozen armed plans.

This is the second tier of the two-tier signal architecture. It never
re-scores or re-classifies anything: the nightly pipeline froze the plan,
and this job only answers "has price crossed a frozen level?" - an event
that cannot repaint. Each plan alerts at most once (status transition),
so there is no cooldown logic to get wrong.
"""
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .armed_plans import active_plans, expire_stale_plans, load_plans, save_plans
from .config import AppConfig
from .emailer import send_email
from .timeutils import is_regular_us_market_hours, now_us_eastern


logger = logging.getLogger(__name__)

PriceFetcher = Callable[[str], Optional[float]]


def run_intraday_check(
    config: AppConfig | None = None,
    price_fetcher: PriceFetcher | None = None,
    now_et: datetime | None = None,
) -> int:
    import time as _time

    from .health import intraday_heartbeat, utc_now_iso, write_health

    config = config or AppConfig.from_env()
    now_et = now_et or now_us_eastern()
    heartbeat_started = utc_now_iso()
    heartbeat_t0 = _time.monotonic()
    if not is_regular_us_market_hours(now_et):
        logger.info("Intraday check skipped: outside regular US market hours.")
        return 0

    path = getattr(config, "armed_plans_path", None)
    if not path:
        logger.info("Intraday check skipped: no armed plans path configured.")
        return 0

    plans = load_plans(path)
    changed = expire_stale_plans(plans, now_et.date())
    candidates = active_plans(plans)
    if not candidates:
        if changed:
            save_plans(path, plans)
        logger.info("Intraday check: no armed plans.")
        return 0

    fetch = price_fetcher or _latest_price
    transitions = 0
    for plan in candidates:
        symbol = plan.get("symbol", "")
        price = fetch(symbol)
        if price is None:
            logger.warning("Intraday check: no price for %s; will retry next run.", symbol)
            continue
        transition = evaluate_plan(plan, price)
        if transition is None:
            continue
        transitions += 1
        plan["status"] = transition
        plan["resolved_at"] = now_et.isoformat()
        plan["resolved_price"] = round(float(price), 4)
        changed = True
        subject, body = compose_trigger_alert(plan, price, transition, now_et)
        if config.dry_run:
            print(subject)
            print(body)
        else:
            send_email(config.smtp, subject, body)
        logger.info("Intraday %s: %s at %.2f", transition, symbol, price)

    if changed:
        save_plans(path, plans)
        _mirror_to_dashboard(config, plans)
    if not getattr(config, "dry_run", False):
        write_health(
            getattr(config, "export_dir", ""),
            intraday_heartbeat(
                checked_plans=len(candidates),
                transitions=transitions,
                started_at=heartbeat_started,
                duration_seconds=_time.monotonic() - heartbeat_t0,
            ),
        )
    return 0


def run_premarket_briefing(
    config: AppConfig | None = None,
    close_fetcher: Callable[[str], Optional[float]] | None = None,
    now_et: datetime | None = None,
) -> int:
    """Email a pre-market readiness digest for armed plans.

    This is NOT a trigger check: it never reads extended-hours quotes and
    never changes plan status. It reports, per active plan, how far the
    last COMPLETED daily close sits from the frozen entry zone and stop -
    so you walk into the open knowing which plans are near action. Runs
    once before the open; disabled with PREMARKET_BRIEFING_ENABLED=false.
    """
    config = config or AppConfig.from_env()
    now_et = now_et or now_us_eastern()
    if not getattr(config, "premarket_briefing_enabled", True):
        logger.info("Pre-market briefing disabled.")
        return 0
    # DST guard: the workflow fires at both 13:00 and 14:00 UTC to cover
    # EDT/EST, but only one of those is 09:00 ET on any given day. Send
    # only in the 9:00-9:29 ET window so exactly one digest goes out.
    if now_et.weekday() >= 5 or now_et.hour != 9 or now_et.minute >= 30:
        logger.info("Pre-market briefing skipped: not in the 09:00-09:29 ET window.")
        return 0
    path = getattr(config, "armed_plans_path", None)
    if not path:
        return 0

    plans = active_plans(load_plans(path))
    if not plans:
        logger.info("Pre-market briefing: no armed plans.")
        return 0

    fetch = close_fetcher or _latest_daily_close
    rows: list[dict[str, Any]] = []
    for plan in plans:
        close = fetch(plan.get("symbol", ""))
        rows.append(_premarket_row(plan, close))
    if not rows:
        return 0

    subject, body = compose_premarket_briefing(rows, now_et)
    if config.dry_run:
        print(subject)
        print(body)
    else:
        send_email(config.smtp, subject, body)
    logger.info("Pre-market briefing sent for %d armed plan(s).", len(rows))
    return 0


def _premarket_row(plan: dict[str, Any], close: Optional[float]) -> dict[str, Any]:
    entry_low = _as_float(plan.get("entry_low"))
    entry_high = _as_float(plan.get("entry_high"))
    stop = _as_float(plan.get("stop_price"))
    row = {
        "symbol": plan.get("symbol", "?"),
        "plan_kind": plan.get("plan_kind", ""),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_price": stop,
        "prev_close": close,
        "dist_to_entry_pct": None,
        "in_zone": False,
        "below_stop": False,
    }
    if close is None or close <= 0:
        return row
    if entry_low is not None and entry_high is not None:
        if entry_low <= close <= entry_high:
            row["in_zone"] = True
            row["dist_to_entry_pct"] = 0.0
        else:
            nearest = entry_low if close < entry_low else entry_high
            row["dist_to_entry_pct"] = round((nearest - close) / close * 100, 2)
    if stop is not None and close <= stop:
        row["below_stop"] = True
    return row


def compose_premarket_briefing(
    rows: list[dict[str, Any]], now_et: datetime
) -> tuple[str, str]:
    stamp = now_et.strftime("%Y-%m-%d %H:%M ET")
    near = [r for r in rows if r["dist_to_entry_pct"] is not None and abs(r["dist_to_entry_pct"]) <= 1.0]
    subject = f"Pre-market readiness: {len(rows)} armed plan(s), {len(near)} near trigger ({stamp})"
    lines = [
        f"Pre-market readiness digest ({stamp})",
        "",
        "Distance from the last completed daily close to each frozen plan.",
        "This is NOT a trigger - extended-hours prices are not used. The",
        "intraday job checks live levels once the regular session opens.",
        "",
    ]
    for row in sorted(rows, key=lambda r: abs(r["dist_to_entry_pct"]) if r["dist_to_entry_pct"] is not None else 1e9):
        symbol = row["symbol"]
        if row["prev_close"] is None:
            lines.append(f"{symbol}: previous close unavailable.")
            continue
        if row["below_stop"]:
            state = "AT/BELOW STOP on the prior close - the setup may be breaking down"
        elif row["in_zone"]:
            state = "INSIDE the entry zone on the prior close - watch the open closely"
        else:
            pct = row["dist_to_entry_pct"]
            direction = "above" if pct < 0 else "below"
            state = f"{abs(pct):.2f}% {direction} the entry zone"
        lines.append(
            f"{symbol} ({row['plan_kind']}): prev close ${row['prev_close']:.2f} -> {state}"
        )
        lines.append(
            f"   entry ${_fmt(row['entry_low'])}-${_fmt(row['entry_high'])} | stop ${_fmt(row['stop_price'])}"
        )
    lines += ["", "No automatic orders. Review before acting."]
    return subject, "\n".join(lines)


def _latest_daily_close(symbol: str) -> Optional[float]:
    """Last COMPLETED daily close via yfinance (trimmed of any forming bar)."""
    try:
        import yfinance as yf

        from .data import trim_incomplete_bars

        history = yf.Ticker(symbol).history(period="10d", interval="1d")
        history = trim_incomplete_bars(history, "1d")
        if history is not None and not history.empty:
            return float(history["Close"].iloc[-1])
    except Exception:
        logger.warning("%s: pre-market close fetch failed.", symbol, exc_info=True)
    return None


def _mirror_to_dashboard(config: Any, plans: list[dict[str, Any]]) -> None:
    export_dir = getattr(config, "export_dir", "")
    if not export_dir:
        return
    try:
        from .export import export_armed_plans

        export_armed_plans(export_dir, plans)
    except Exception:
        logger.warning("Armed-plan dashboard mirror failed.", exc_info=True)


def evaluate_plan(plan: dict[str, Any], price: float) -> Optional[str]:
    """Level rules on the frozen plan. Order matters: stop wins over entry.

    - price at/below the frozen stop -> invalidated (setup broke down)
    - price inside the frozen entry zone -> triggered (executable)
    - price above the zone (breakout ran away) -> stay armed; discipline
      says don't chase, and a pullback into the zone can still trigger.
    """
    stop = _as_float(plan.get("stop_price"))
    entry_low = _as_float(plan.get("entry_low"))
    entry_high = _as_float(plan.get("entry_high"))
    if stop is not None and price <= stop:
        return "invalidated"
    if entry_low is not None and entry_high is not None and entry_low <= price <= entry_high:
        return "triggered"
    return None


def compose_trigger_alert(
    plan: dict[str, Any], price: float, transition: str, now_et: datetime
) -> tuple[str, str]:
    symbol = plan.get("symbol", "?")
    kind = plan.get("plan_kind", "buy")
    stamp = now_et.strftime("%Y-%m-%d %H:%M ET")
    if transition == "triggered":
        subject = f"{symbol} TRIGGER: ${price:.2f} entered the frozen entry zone ({kind})"
        headline = "Price entered the entry zone frozen by last night's plan."
    else:
        subject = f"{symbol} PLAN INVALIDATED: ${price:.2f} at/below frozen stop"
        headline = "Price broke the frozen stop before entry; the plan is cancelled."
    lines = [
        f"{symbol} intraday level alert ({stamp})",
        "",
        headline,
        "",
        f"plan: {kind} / {plan.get('setup_type', 'n/a')} | score at arm time {plan.get('score', 'n/a')}",
        f"entry zone: ${_fmt(plan.get('entry_low'))} - ${_fmt(plan.get('entry_high'))}",
        f"stop: ${_fmt(plan.get('stop_price'))} | targets: ${_fmt(plan.get('target1'))} / ${_fmt(plan.get('target2'))}",
        f"risk budget: position {plan.get('position_pct', 0):.2f}% | max loss {plan.get('max_loss_pct', 0):.2f}%",
        f"armed: {plan.get('created_date')} | expires: {plan.get('expires_date')}",
        f"last price: ${price:.2f}",
        "",
        "This is a level-crossing event against a frozen plan, not a fresh signal.",
        "No automatic orders. Review before acting.",
    ]
    return subject, "\n".join(lines)


def _latest_price(symbol: str) -> Optional[float]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
    except Exception:
        logger.warning("%s: yfinance unavailable for intraday price.", symbol, exc_info=True)
        return None

    try:
        fast_info = ticker.fast_info
        for key in ("last_price", "lastPrice"):
            value = None
            try:
                value = fast_info[key]
            except Exception:
                value = getattr(fast_info, key, None)
            if value:
                return float(value)
    except Exception:
        logger.info("%s: fast_info unavailable; falling back to intraday history.", symbol)

    try:
        history = ticker.history(period="1d", interval="5m")
        if history is not None and not history.empty:
            return float(history["Close"].iloc[-1])
    except Exception:
        logger.warning("%s: intraday price fallback failed.", symbol, exc_info=True)
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _fmt(value: Any) -> str:
    number = _as_float(value)
    return "NA" if number is None else f"{number:.2f}"
