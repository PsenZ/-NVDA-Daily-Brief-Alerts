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
    config = config or AppConfig.from_env()
    now_et = now_et or now_us_eastern()
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
    for plan in candidates:
        symbol = plan.get("symbol", "")
        price = fetch(symbol)
        if price is None:
            logger.warning("Intraday check: no price for %s; will retry next run.", symbol)
            continue
        transition = evaluate_plan(plan, price)
        if transition is None:
            continue
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
    return 0


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
