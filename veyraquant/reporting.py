from datetime import datetime

from .config import AppConfig
from .models import MarketContext, SignalResult
from .timeutils import US_EASTERN_TZ


def format_money(value) -> str:
    if value is None:
        return "NA"
    try:
        value = float(value)
    except Exception:
        return "NA"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:.2f}"


def format_dual_time(now_dt: datetime) -> str:
    eastern_dt = now_dt.astimezone(US_EASTERN_TZ)
    return (
        f"Sydney {now_dt.strftime('%Y-%m-%d %H:%M')} / "
        f"US Eastern {eastern_dt.strftime('%Y-%m-%d %H:%M')}"
    )


def compose_daily_report(
    results: list[SignalResult],
    market: MarketContext,
    config: AppConfig,
    now_dt: datetime,
    portfolio_notes: list[str] | None = None,
) -> tuple[str, str]:
    subject = f"{config.subject_prefix} - {now_dt.strftime('%Y-%m-%d')}"
    dual_time = format_dual_time(now_dt)

    approved = [item for item in results if item.portfolio_decision == "approved"][:3]
    watchlist = [
        item
        for item in results
        if item.portfolio_decision in {"watchlist", "deferred"} and item.action not in {"RISK_REDUCE", "REJECT"}
    ]
    risk_actions = [item for item in results if item.action == "RISK_REDUCE"]
    rejected = [item for item in results if item.action == "REJECT"]
    deferred_count = len([item for item in results if item.portfolio_decision == "deferred"])

    lines: list[str] = [
        "VeyraQuant Morning Brief",
        f"Time: {dual_time}",
        "",
        "[Executive Summary]",
        f"market_regime: {market.label}",
        f"trading_posture: {_trading_posture(market, len(approved))}",
        (
            f"approved {len(approved)} | deferred {deferred_count} | "
            f"watchlist {len(watchlist)} | rejected {len(rejected)}"
        ),
        _summary_line(market, approved, deferred_count),
        _key_risk_line(market, results),
        "",
        "[Market Filter]",
        f"market_score: {market.score:+.1f}",
        *[f"- {reason}" for reason in market.reasons[:3]],
    ]
    if market.risks:
        lines.extend(f"- risk: {risk}" for risk in market.risks[:2])
    lines.extend(_market_snapshot_lines(market))

    lines.extend(["", "[Top Actions]"])
    if not approved:
        lines.append("No approved trade plans today.")
    for result in approved:
        lines.extend(_top_action_block(result))

    lines.extend(["", "[Watchlist]"])
    if not watchlist:
        lines.append("No watchlist names today.")
    else:
        lines.append("symbol | rating | score | next condition | why not now")
        for result in watchlist:
            lines.append(_watchlist_row(result))

    lines.extend(["", "[Risk Actions]"])
    if not risk_actions:
        lines.append("No active risk-reduction signals today.")
    for result in risk_actions:
        lines.extend(_risk_action_block(result))

    lines.extend(["", "[Rejected Plans]"])
    if not rejected:
        lines.append("No rejected plans today.")
    for result in rejected:
        lines.extend(_rejected_block(result))

    lines.extend(["", "[System Notes]"])
    notes = _system_notes(results, portfolio_notes or [])
    if notes:
        lines.extend(notes)
    else:
        lines.append("- No additional system notes.")
    lines.extend(
        [
            "- No broker API. No automatic orders. Every trade plan requires human review.",
            "- Position sizing follows existing risk controls and may be reduced by portfolio heat.",
        ]
    )
    return subject, "\n".join(lines)


def compose_alert_email(result: SignalResult, now_dt: datetime) -> tuple[str, str]:
    dual_time = format_dual_time(now_dt)
    if result.action == "RISK_REDUCE":
        subject = f"{result.symbol} Risk Alert - {result.rating} - score {result.score}"
        lines = [
            f"{result.symbol} Risk Alert ({dual_time})",
            "",
            f"rating/action: {result.rating} / {result.action}",
            f"score: {result.score}",
            f"market_regime: {result.market_regime}",
            f"risk reason: {_compact_summary(result.bear_case or result.risks, 2)}",
            f"suggested posture: {result.portfolio_reason or 'Reduce exposure and avoid adding new size.'}",
            f"market evidence: {_compact_summary(result.market_evidence, 1)}",
            "",
            "No buy/add trade plan is attached to this risk alert.",
        ]
        return subject, "\n".join(lines)

    subject = f"{result.symbol} {result.rating} / {result.action} - score {result.score}"
    lines = [
        f"{result.symbol} Trade Alert ({dual_time})",
        "",
        f"rating/action: {result.rating} / {result.action}",
        f"score/setup: {result.score} / {result.setup_type}",
        f"plan: {result.entry_zone} | stop {result.stop} | targets {result.targets}",
        f"risk budget: position {result.position_pct:.2f}% | max loss {result.max_loss_pct:.2f}%",
        f"why now: {_compact_summary(result.bull_case, 2)}",
        f"watch risk: {_compact_summary(result.bear_case, 2)}",
        f"market evidence: {_compact_summary(result.market_evidence, 1)}",
        f"trigger / cancel: {result.trade_plan.trigger} / {result.trade_plan.cancel}",
    ]
    if result.validation_warnings:
        lines.append(f"validation warning: {_compact_summary(result.validation_warnings, 1)}")
    return subject, "\n".join(lines)


def _trading_posture(market: MarketContext, approved_count: int) -> str:
    if market.label == "\u98ce\u9669\u89c4\u907f":
        return "Defense first"
    if approved_count > 0:
        return "Selective execution"
    if market.label == "\u98ce\u9669\u504f\u597d":
        return "Stay patient for cleaner entries"
    return "Neutral and patient"


def _summary_line(market: MarketContext, approved: list[SignalResult], deferred_count: int) -> str:
    if approved:
        leaders = ", ".join(item.symbol for item in approved[:2])
        return (
            f"The board is constructive enough to approve {len(approved)} trade plan(s), "
            f"led by {leaders}, while {deferred_count} candidate(s) remain on hold."
        )
    if market.label == "\u98ce\u9669\u89c4\u907f":
        return "The board stays defensive today and fresh execution should remain tightly filtered."
    return "No plan earned full approval today, so the focus shifts to watching for better alignment."


def _key_risk_line(market: MarketContext, results: list[SignalResult]) -> str:
    candidate_risks = list(market.risks)
    for result in results:
        if result.validation_warnings:
            candidate_risks.extend(result.validation_warnings)
        candidate_risks.extend(result.bear_case[:1])
    return f"key_risk: {_compact_summary(candidate_risks, 1)}"


def _market_snapshot_lines(market: MarketContext) -> list[str]:
    lines: list[str] = []
    for symbol in ["SPY", "QQQ", "SMH", "^VIX"]:
        snapshot = market.snapshots.get(symbol)
        if not snapshot:
            continue
        if snapshot.get("status") == "missing":
            lines.append(f"- {symbol}: data missing")
            continue
        if symbol == "^VIX":
            last = snapshot.get("last")
            if last is not None:
                lines.append(f"- ^VIX: last {float(last):.2f}")
            continue
        pieces = []
        for key in ("last", "sma20", "sma50", "perf20"):
            value = snapshot.get(key)
            if value is None:
                continue
            if key == "perf20":
                pieces.append(f"{key} {float(value):+.2f}%")
            else:
                pieces.append(f"{key} {float(value):.2f}")
        if pieces:
            lines.append(f"- {symbol}: " + ", ".join(pieces))
    return lines


def _top_action_block(result: SignalResult) -> list[str]:
    lines = [
        "",
        f"## {result.symbol}",
        f"rating/action: {result.rating} / {result.action}",
        f"score/setup: {result.score} / {result.setup_type}",
        f"plan: {result.entry_zone} | stop {result.stop} | targets {result.targets}",
        f"risk budget: position {result.position_pct:.2f}% | max loss {result.max_loss_pct:.2f}%",
        f"why now: {_compact_summary(result.bull_case, 2)}",
        f"watch risk: {_compact_summary(result.bear_case, 2)}",
        f"market evidence: {_compact_summary(result.market_evidence, 1)}",
        f"trigger / cancel: {result.trade_plan.trigger} / {result.trade_plan.cancel}",
    ]
    if result.validation_warnings:
        lines.append(f"validation warning: {_compact_summary(result.validation_warnings, 1)}")
    return lines


def _watchlist_row(result: SignalResult) -> str:
    next_condition = result.trade_plan.trigger or "Wait for better alignment."
    why_not_now = result.portfolio_reason or _compact_summary(result.bear_case or result.risks, 1)
    return (
        f"{result.symbol} | {result.rating} | {result.score} | "
        f"{next_condition} | {why_not_now}"
    )


def _risk_action_block(result: SignalResult) -> list[str]:
    return [
        "",
        f"{result.symbol} | {result.rating} | score {result.score}",
        f"risk reason: {_compact_summary(result.bear_case or result.risks, 2)}",
        f"suggested posture: {result.portfolio_reason or 'Reduce exposure and avoid adding risk.'}",
    ]


def _rejected_block(result: SignalResult) -> list[str]:
    return [
        "",
        f"{result.symbol} | score {result.score}",
        f"why rejected: {_compact_summary(result.rejection_reasons or result.bear_case, 2)}",
        f"blocked_by: {_compact_summary(result.suppressed_by, 2)}",
    ]


def _system_notes(results: list[SignalResult], portfolio_notes: list[str]) -> list[str]:
    lines: list[str] = []
    data_warnings = _unique([warning for result in results for warning in result.warnings])
    validation_warnings = _unique(
        [warning for result in results for warning in result.validation_warnings]
    )
    heat_warnings = _unique(
        [warning for result in results for warning in result.portfolio_warnings]
    )

    if data_warnings:
        lines.extend(["- data warnings:"] + [f"  - {item}" for item in data_warnings[:6]])
    if validation_warnings:
        lines.extend(["- validation warnings:"] + [f"  - {item}" for item in validation_warnings[:6]])
    if heat_warnings:
        lines.extend(["- portfolio heat warnings:"] + [f"  - {item}" for item in heat_warnings[:6]])
    if portfolio_notes:
        lines.extend(["- portfolio notes:"] + [f"  - {item}" for item in _unique(portfolio_notes)[:6]])
    return lines


def _compact_summary(items: list[str], limit: int = 2) -> str:
    filtered = [item for item in items if item]
    if not filtered:
        return "None."
    return " ; ".join(filtered[:limit])


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
