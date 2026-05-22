from datetime import datetime
from html import escape

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
    review_notes: list[str] | None = None,
) -> tuple[str, str]:
    subject = f"{config.subject_prefix} - {now_dt.strftime('%Y-%m-%d')}"
    dual_time = format_dual_time(now_dt)

    approved = [item for item in results if item.portfolio_decision == "approved"][:3]
    deferred_ideas = [
        item
        for item in results
        if item.portfolio_decision == "deferred" and item.action not in {"RISK_REDUCE", "REJECT"}
    ]
    watchlist = [
        item
        for item in results
        if item.portfolio_decision == "watchlist" and item.action in {"WATCH", "WAIT"}
    ]
    risk_actions = [item for item in results if item.action == "RISK_REDUCE"]
    rejected = [item for item in results if item.action == "REJECT"]
    deferred_count = len(deferred_ideas)

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

    lines.extend(["", "[Deferred Ideas]"])
    if not deferred_ideas:
        lines.append("No deferred high-conviction ideas today.")
    else:
        lines.append("symbol | rating | score | conviction | why still good | why not today")
        for result in deferred_ideas:
            lines.append(_deferred_row(result))

    lines.extend(["", "[Watch / Wait]"])
    if not watchlist:
        lines.append("No watch / wait names today.")
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
    notes = _system_notes(results, portfolio_notes or [], review_notes or [])
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
        position_context = getattr(result, "position_context", "No open position.")
        suggested_posture = getattr(result, "suggested_posture", "monitor-only")
        subject = f"{result.symbol} Risk Alert - {result.rating} - score {_score_label(result)}"
        lines = [
            f"{result.symbol} Risk Alert ({dual_time})",
            "",
            f"rating/action: {result.rating} / {result.action}",
            f"score: {_score_label(result)}",
            f"market_regime: {result.market_regime}",
            f"risk reason: {_compact_summary(result.bear_case or result.risks, 2)}",
            f"position_context: {position_context}",
            f"suggested posture: {suggested_posture}",
            f"risk note: {result.portfolio_reason or 'Monitor the risk condition.'}",
            f"market evidence: {_compact_summary(result.market_evidence, 1)}",
            "",
            "No buy/add trade plan is attached to this risk alert.",
        ]
        return subject, "\n".join(lines)

    subject = f"{result.symbol} {result.rating} / {result.action} - score {_score_label(result)}"
    lines = [
        f"{result.symbol} Trade Alert ({dual_time})",
        "",
        f"rating/action: {result.rating} / {result.action}",
        f"score/setup: {_score_label(result)} / {result.setup_type}",
        f"data_quality: {result.data_quality.data_quality_level}",
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


def compose_daily_report_html(
    results: list[SignalResult],
    market: MarketContext,
    config: AppConfig,
    now_dt: datetime,
    portfolio_notes: list[str] | None = None,
    review_notes: list[str] | None = None,
) -> str:
    _subject, plain = compose_daily_report(results, market, config, now_dt, portfolio_notes, review_notes)
    sections = _plain_sections(plain)
    blocks = [
        "<!doctype html><html><body style=\"margin:0;background:#0f172a;color:#e5e7eb;font-family:Arial,sans-serif;\">",
        "<div style=\"max-width:860px;margin:0 auto;padding:24px;\">",
        "<h1 style=\"margin:0 0 8px;font-size:24px;\">VeyraQuant Morning Brief</h1>",
        f"<p style=\"margin:0 0 20px;color:#93c5fd;\">{escape(format_dual_time(now_dt))}</p>",
    ]
    for title, content in sections:
        blocks.append(_html_section(title, content))
    blocks.append("</div></body></html>")
    return "\n".join(blocks)


def compose_alert_email_html(result: SignalResult, now_dt: datetime) -> str:
    _subject, plain = compose_alert_email(result, now_dt)
    lines = [line for line in plain.splitlines() if line.strip()]
    title = escape(lines[0]) if lines else escape(result.symbol)
    rows = "".join(f"<p style=\"margin:6px 0;\">{escape(line)}</p>" for line in lines[1:])
    border = "#f97316" if result.action == "RISK_REDUCE" else "#22c55e"
    return (
        "<!doctype html><html><body style=\"margin:0;background:#111827;color:#e5e7eb;font-family:Arial,sans-serif;\">"
        "<div style=\"max-width:720px;margin:0 auto;padding:24px;\">"
        f"<div style=\"border-left:4px solid {border};padding:16px;background:#1f2937;\">"
        f"<h1 style=\"margin:0 0 12px;font-size:22px;\">{title}</h1>{rows}"
        "</div></div></body></html>"
    )


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
        f"score/setup: {_score_label(result)} / {result.setup_type}",
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


def _deferred_row(result: SignalResult) -> str:
    return (
        f"{result.symbol} | {result.rating} | {_score_label(result)} | {result.conviction_level} | "
        f"{_compact_summary(result.bull_case, 1)} | {result.portfolio_reason}"
    )


def _watchlist_row(result: SignalResult) -> str:
    next_condition = result.trade_plan.trigger or "Wait for better alignment."
    why_not_now = result.portfolio_reason or _compact_summary(result.bear_case or result.risks, 1)
    return (
        f"{result.symbol} | {result.rating} | {_score_label(result)} | "
        f"{next_condition} | {why_not_now}"
    )


def _risk_action_block(result: SignalResult) -> list[str]:
    position_context = getattr(result, "position_context", "No open position.")
    suggested_posture = getattr(result, "suggested_posture", "monitor-only")
    return [
        "",
        f"{result.symbol} | {result.rating} | score {_score_label(result)}",
        f"risk reason: {_compact_summary(result.bear_case or result.risks, 2)}",
        f"position_context: {position_context}",
        f"suggested posture: {suggested_posture}",
        f"risk note: {result.portfolio_reason or 'Monitor the risk condition.'}",
    ]


def _rejected_block(result: SignalResult) -> list[str]:
    return [
        "",
        f"{result.symbol} | score {_score_label(result)}",
        f"why rejected: {_compact_summary(result.rejection_reasons or result.bear_case, 2)}",
        f"blocked_by: {_compact_summary(result.suppressed_by, 2)}",
    ]


def _system_notes(results: list[SignalResult], portfolio_notes: list[str], review_notes: list[str]) -> list[str]:
    lines: list[str] = []
    data_warnings = _unique([warning for result in results for warning in result.warnings])
    validation_warnings = _unique(
        [warning for result in results for warning in result.validation_warnings]
    )
    heat_warnings = _unique(
        [warning for result in results for warning in result.portfolio_warnings]
    )
    data_quality_notes = _unique(
        [
            f"{result.symbol}: {result.data_quality.data_quality_level} - "
            f"{_compact_summary(result.data_quality.reasons, 2)}"
            for result in results
            if result.data_quality.data_quality_level != "HIGH" or result.data_quality.reasons
        ]
    )

    if data_warnings:
        lines.extend(["- data warnings:"] + [f"  - {item}" for item in data_warnings[:6]])
    if data_quality_notes:
        lines.extend(["- data quality:"] + [f"  - {item}" for item in data_quality_notes[:6]])
    if validation_warnings:
        lines.extend(["- validation warnings:"] + [f"  - {item}" for item in validation_warnings[:6]])
    if heat_warnings:
        lines.extend(["- portfolio heat warnings:"] + [f"  - {item}" for item in heat_warnings[:6]])
    if portfolio_notes:
        lines.extend(["- portfolio notes:"] + [f"  - {item}" for item in _unique(portfolio_notes)[:6]])
    if review_notes:
        lines.extend(["- decision review:"] + [f"  - {item}" for item in _unique(review_notes)[:4]])
    return lines


def _plain_sections(body: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    title = "Header"
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("[") and line.endswith("]"):
            if current:
                sections.append((title, current))
            title = line.strip("[]")
            current = []
        else:
            current.append(line)
    if current:
        sections.append((title, current))
    return sections


def _html_section(title: str, lines: list[str]) -> str:
    accent = {
        "Top Actions": "#22c55e",
        "Deferred Ideas": "#38bdf8",
        "Watch / Wait": "#a3e635",
        "Risk Actions": "#f97316",
        "Rejected Plans": "#ef4444",
    }.get(title, "#64748b")
    content = "<br>".join(escape(line) for line in lines if line != "")
    return (
        f"<section style=\"border-top:3px solid {accent};background:#1f2937;"
        "padding:16px;margin:0 0 14px;border-radius:6px;\">"
        f"<h2 style=\"margin:0 0 10px;font-size:18px;color:#f8fafc;\">{escape(title)}</h2>"
        f"<div style=\"font-size:14px;line-height:1.55;color:#d1d5db;\">{content}</div>"
        "</section>"
    )


def _compact_summary(items: list[str], limit: int = 2) -> str:
    filtered = [item for item in items if item]
    if not filtered:
        return "None."
    return " ; ".join(filtered[:limit])


def _score_label(result: SignalResult) -> str:
    if result.score >= 100 and result.raw_score > 100:
        return "100+"
    return str(result.score)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
