from datetime import datetime
from html import escape

from .config import AppConfig
from .constants import MARKET_RISK_OFF, MARKET_RISK_ON
from .models import MarketContext, SignalResult
from .text_utils import dedupe
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
    research_notes: dict | None = None,
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

    if research_notes:
        lines.extend(["", "[Research Notes]"])
        lines.append("LLM commentary on structured evidence only; not part of any decision.")
        for symbol in sorted(research_notes):
            note = research_notes[symbol]
            lines.append(f"-- {symbol} --")
            lines.append(f"thesis: {note.get('thesis', '')}")
            lines.append(f"counter: {note.get('counter_thesis', '')}")
            lines.append(f"uncertainty: {note.get('uncertainty', '')}")

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


# Email-safe light palette (inline styles only; email clients strip <style>
# and often ignore @media, so a single client-robust light scheme is used
# rather than an unreliable dark/light toggle).
_HTML_BG = "#f4f6f9"
_HTML_CARD = "#ffffff"
_HTML_TEXT = "#1a1f2b"
_HTML_MUTED = "#5b6472"
_HTML_HEAD = "#0f1826"
_HTML_ACCENT = "#3459c4"
_HTML_ROW_ALT = "#f1f4f8"
_HTML_BORDER = "#dfe4ec"
_SECTION_ACCENT = {
    "Top Actions": "#15a34a",
    "Deferred Ideas": "#2563c9",
    "Watch / Wait": "#4d8a12",
    "Risk Actions": "#d9700a",
    "Rejected Plans": "#d13d33",
}


def compose_daily_report_html(
    results: list[SignalResult],
    market: MarketContext,
    config: AppConfig,
    now_dt: datetime,
    portfolio_notes: list[str] | None = None,
    review_notes: list[str] | None = None,
) -> str:
    """Render the brief directly from structured data (not by re-parsing plain text)."""
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

    blocks = [
        f"<!doctype html><html><body style=\"margin:0;background:{_HTML_BG};color:{_HTML_TEXT};"
        "font-family:Arial,Helvetica,sans-serif;\">",
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        f"style=\"background:{_HTML_BG};\"><tr><td align=\"center\" style=\"padding:24px 12px;\">",
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"max-width:640px;width:100%;\"><tr><td>",
        f"<h1 style=\"margin:0 0 6px;font-size:22px;color:{_HTML_HEAD};\">VeyraQuant Morning Brief</h1>",
        f"<p style=\"margin:0 0 20px;font-size:13px;color:{_HTML_ACCENT};\">"
        f"{escape(format_dual_time(now_dt))}</p>",
        _html_summary_card(market, approved, deferred_ideas, watchlist, rejected, results),
        _html_market_card(market),
        _html_top_actions_card(approved),
        _html_table_card(
            "Deferred Ideas",
            ["Symbol", "Rating", "Score", "Conviction", "Why still good", "Why not today"],
            [_deferred_cells(r) for r in deferred_ideas],
            empty="No deferred high-conviction ideas today.",
        ),
        _html_table_card(
            "Watch / Wait",
            ["Symbol", "Rating", "Score", "Next condition", "Why not now"],
            [_watchlist_cells(r) for r in watchlist],
            empty="No watch / wait names today.",
        ),
        _html_risk_actions_card(risk_actions),
        _html_rejected_card(rejected),
        _html_notes_card(results, portfolio_notes or [], review_notes or []),
        f"<p style=\"margin:18px 0 0;font-size:11px;color:{_HTML_MUTED};line-height:1.5;\">"
        "No broker API. No automatic orders. Every trade plan requires human review. "
        "Position sizing follows existing risk controls and may be reduced by portfolio heat.</p>",
        "</td></tr></table></td></tr></table></body></html>",
    ]
    return "\n".join(blocks)


def compose_alert_email_html(result: SignalResult, now_dt: datetime) -> str:
    is_risk = result.action == "RISK_REDUCE"
    border = _SECTION_ACCENT["Risk Actions"] if is_risk else _SECTION_ACCENT["Top Actions"]
    dual_time = format_dual_time(now_dt)
    kind = "Risk Alert" if is_risk else "Trade Alert"
    title = f"{result.symbol} {kind}"

    if is_risk:
        rows = (
            _html_kv("rating / action", f"{result.rating} / {result.action}")
            + _html_kv("score", _score_label(result))
            + _html_kv("market_regime", result.market_regime)
            + _html_kv("risk reason", _compact_summary(result.bear_case or result.risks, 2))
            + _html_kv("position", getattr(result, "position_context", "No open position."))
            + _html_kv("suggested posture", getattr(result, "suggested_posture", "monitor-only"))
            + _html_kv("risk note", result.portfolio_reason or "Monitor the risk condition.")
        )
    else:
        rows = (
            _html_kv("rating / action", f"{result.rating} / {result.action}")
            + _html_kv("score / setup", f"{_score_label(result)} / {result.setup_type}")
            + _html_kv("data_quality", result.data_quality.data_quality_level)
            + _html_kv("plan", f"{result.entry_zone} | stop {result.stop} | targets {result.targets}")
            + _html_kv(
                "risk budget",
                f"position {result.position_pct:.2f}% | max loss {result.max_loss_pct:.2f}%",
            )
            + _html_kv("why now", _compact_summary(result.bull_case, 2))
            + _html_kv("watch risk", _compact_summary(result.bear_case, 2))
            + _html_kv("market evidence", _compact_summary(result.market_evidence, 1))
            + _html_kv(
                "trigger / cancel", f"{result.trade_plan.trigger} / {result.trade_plan.cancel}"
            )
        )
        if result.validation_warnings:
            rows += _html_kv("validation warning", _compact_summary(result.validation_warnings, 1))

    return (
        f"<!doctype html><html><body style=\"margin:0;background:{_HTML_BG};color:{_HTML_TEXT};"
        "font-family:Arial,Helvetica,sans-serif;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        f"style=\"background:{_HTML_BG};\"><tr><td align=\"center\" style=\"padding:24px 12px;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        f"style=\"max-width:560px;width:100%;background:{_HTML_CARD};border-left:4px solid {border};"
        "border-radius:6px;\"><tr><td style=\"padding:18px 20px;\">"
        f"<h1 style=\"margin:0 0 4px;font-size:19px;color:{_HTML_HEAD};\">{escape(title)}</h1>"
        f"<p style=\"margin:0 0 14px;font-size:12px;color:{_HTML_ACCENT};\">{escape(dual_time)}</p>"
        f"{rows}"
        "</td></tr></table></td></tr></table></body></html>"
    )


def _html_card(title: str, inner: str, accent: str | None = None) -> str:
    accent = accent or _SECTION_ACCENT.get(title, "#64748b")
    heading = (
        f"<h2 style=\"margin:0 0 12px;font-size:15px;color:{_HTML_HEAD};"
        f"letter-spacing:0.02em;\">{escape(title)}</h2>"
        if title
        else ""
    )
    return (
        f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        f"style=\"background:{_HTML_CARD};border-top:3px solid {accent};"
        "border-radius:6px;margin:0 0 14px;\"><tr><td style=\"padding:16px 18px;\">"
        f"{heading}{inner}</td></tr></table>"
    )


def _html_kv(label: str, value: str) -> str:
    return (
        f"<p style=\"margin:0 0 6px;font-size:13px;color:{_HTML_TEXT};line-height:1.5;\">"
        f"<span style=\"color:{_HTML_MUTED};\">{escape(label)}: </span>{escape(value)}</p>"
    )


def _html_summary_card(market, approved, deferred, watchlist, rejected, results) -> str:
    counts = (
        f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"margin:0 0 10px;\"><tr>"
        + "".join(
            f"<td style=\"padding:0 14px 0 0;font-size:13px;color:{_HTML_TEXT};\">"
            f"<span style=\"font-size:20px;font-weight:bold;color:{color};"
            f"font-variant-numeric:tabular-nums;\">{n}</span> "
            f"<span style=\"color:{_HTML_MUTED};\">{label}</span></td>"
            for n, label, color in (
                (len(approved), "approved", _SECTION_ACCENT["Top Actions"]),
                (len(deferred), "deferred", _SECTION_ACCENT["Deferred Ideas"]),
                (len(watchlist), "watch", _SECTION_ACCENT["Watch / Wait"]),
                (len(rejected), "rejected", _SECTION_ACCENT["Rejected Plans"]),
            )
        )
        + "</tr></table>"
    )
    inner = (
        _html_kv("market_regime", market.label)
        + _html_kv("trading_posture", _trading_posture(market, len(approved)))
        + counts
        + f"<p style=\"margin:0 0 6px;font-size:13px;color:{_HTML_TEXT};line-height:1.5;\">"
        + escape(_summary_line(market, approved, len(deferred)))
        + "</p>"
        + _html_kv("key_risk", _key_risk_line(market, results).replace("key_risk: ", "", 1))
    )
    return _html_card("Executive Summary", inner, accent="#64748b")


def _html_market_card(market: MarketContext) -> str:
    inner = _html_kv("market_score", f"{market.score:+.1f}")
    bullets = [f"- {reason}" for reason in market.reasons[:3]]
    bullets += [f"- risk: {risk}" for risk in market.risks[:2]]
    bullets += _market_snapshot_lines(market)
    inner += "".join(
        f"<p style=\"margin:0 0 4px;font-size:13px;color:{_HTML_TEXT};line-height:1.5;\">"
        f"{escape(line)}</p>"
        for line in bullets
    )
    return _html_card("Market Filter", inner, accent="#64748b")


def _html_top_actions_card(approved: list[SignalResult]) -> str:
    if not approved:
        return _html_card(
            "Top Actions",
            f"<p style=\"margin:0;font-size:13px;color:{_HTML_MUTED};\">"
            "No approved trade plans today.</p>",
        )
    blocks = []
    for i, result in enumerate(approved):
        divider = (
            f"<div style=\"border-top:1px solid {_HTML_BORDER};margin:14px 0;\"></div>" if i else ""
        )
        name = (
            f"<p style=\"margin:0 0 8px;font-size:15px;font-weight:bold;color:{_HTML_HEAD};\">"
            f"{escape(result.symbol)} "
            f"<span style=\"font-size:12px;font-weight:normal;color:{_HTML_MUTED};\">"
            f"{escape(result.rating)} / {escape(result.action)}</span></p>"
        )
        plan = (
            f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"margin:0 0 8px;\">"
            + "".join(
                f"<tr><td style=\"padding:1px 16px 1px 0;font-size:12px;color:{_HTML_MUTED};\">{escape(k)}</td>"
                f"<td style=\"padding:1px 0;font-size:13px;color:{_HTML_TEXT};"
                f"font-variant-numeric:tabular-nums;\">{escape(v)}</td></tr>"
                for k, v in (
                    ("score / setup", f"{_score_label(result)} / {result.setup_type}"),
                    ("entry", result.entry_zone),
                    ("stop", result.stop),
                    ("targets", result.targets),
                    ("risk budget", f"position {result.position_pct:.2f}% | max loss {result.max_loss_pct:.2f}%"),
                )
            )
            + "</table>"
        )
        detail = (
            _html_kv("why now", _compact_summary(result.bull_case, 2))
            + _html_kv("watch risk", _compact_summary(result.bear_case, 2))
            + _html_kv("market evidence", _compact_summary(result.market_evidence, 1))
            + _html_kv("trigger / cancel", f"{result.trade_plan.trigger} / {result.trade_plan.cancel}")
        )
        if result.validation_warnings:
            detail += _html_kv("validation warning", _compact_summary(result.validation_warnings, 1))
        blocks.append(divider + name + plan + detail)
    return _html_card("Top Actions", "".join(blocks))


def _html_table_card(title: str, headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return _html_card(
            title, f"<p style=\"margin:0;font-size:13px;color:{_HTML_MUTED};\">{escape(empty)}</p>"
        )
    head = "".join(
        f"<th align=\"left\" style=\"padding:6px 10px;font-size:11px;text-transform:uppercase;"
        f"letter-spacing:0.04em;color:{_HTML_MUTED};border-bottom:1px solid {_HTML_BORDER};"
        f"white-space:nowrap;\">{escape(h)}</th>"
        for h in headers
    )
    body_rows = []
    for idx, cells in enumerate(rows):
        bg = _HTML_ROW_ALT if idx % 2 else _HTML_CARD
        tds = "".join(
            f"<td style=\"padding:6px 10px;font-size:12px;color:{_HTML_TEXT};"
            f"vertical-align:top;font-variant-numeric:tabular-nums;\">{escape(cell)}</td>"
            for cell in cells
        )
        body_rows.append(f"<tr style=\"background:{bg};\">{tds}</tr>")
    table = (
        "<div style=\"overflow-x:auto;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;width:100%;\">"
        f"<tr>{head}</tr>{''.join(body_rows)}</table></div>"
    )
    return _html_card(title, table)


def _html_risk_actions_card(risk_actions: list[SignalResult]) -> str:
    if not risk_actions:
        return _html_card(
            "Risk Actions",
            f"<p style=\"margin:0;font-size:13px;color:{_HTML_MUTED};\">"
            "No active risk-reduction signals today.</p>",
        )
    blocks = []
    for i, result in enumerate(risk_actions):
        divider = (
            f"<div style=\"border-top:1px solid {_HTML_BORDER};margin:14px 0;\"></div>" if i else ""
        )
        name = (
            f"<p style=\"margin:0 0 6px;font-size:14px;font-weight:bold;color:{_HTML_HEAD};\">"
            f"{escape(result.symbol)} "
            f"<span style=\"font-size:12px;font-weight:normal;color:{_HTML_MUTED};\">"
            f"{escape(result.rating)} · score {escape(_score_label(result))}</span></p>"
        )
        detail = (
            _html_kv("risk reason", _compact_summary(result.bear_case or result.risks, 2))
            + _html_kv("position", getattr(result, "position_context", "No open position."))
            + _html_kv("suggested posture", getattr(result, "suggested_posture", "monitor-only"))
            + _html_kv("risk note", result.portfolio_reason or "Monitor the risk condition.")
        )
        blocks.append(divider + name + detail)
    return _html_card("Risk Actions", "".join(blocks))


def _html_rejected_card(rejected: list[SignalResult]) -> str:
    if not rejected:
        return _html_card(
            "Rejected Plans",
            f"<p style=\"margin:0;font-size:13px;color:{_HTML_MUTED};\">No rejected plans today.</p>",
        )
    blocks = []
    for i, result in enumerate(rejected):
        divider = (
            f"<div style=\"border-top:1px solid {_HTML_BORDER};margin:12px 0;\"></div>" if i else ""
        )
        name = (
            f"<p style=\"margin:0 0 6px;font-size:14px;font-weight:bold;color:{_HTML_HEAD};\">"
            f"{escape(result.symbol)} "
            f"<span style=\"font-size:12px;font-weight:normal;color:{_HTML_MUTED};\">"
            f"score {escape(_score_label(result))}</span></p>"
        )
        detail = _html_kv(
            "why rejected", _compact_summary(result.rejection_reasons or result.bear_case, 2)
        ) + _html_kv("blocked_by", _compact_summary(result.suppressed_by, 2))
        blocks.append(divider + name + detail)
    return _html_card("Rejected Plans", "".join(blocks))


def _html_notes_card(results, portfolio_notes, review_notes) -> str:
    lines = _system_notes(results, portfolio_notes, review_notes)
    if not lines:
        return ""
    html_lines = []
    for line in lines:
        indented = line.startswith("  ")
        pad = "18px" if indented else "0"
        weight = "normal" if indented else "bold"
        color = _HTML_TEXT if indented else _HTML_ACCENT
        html_lines.append(
            f"<p style=\"margin:0 0 3px;padding-left:{pad};font-size:12px;color:{color};"
            f"font-weight:{weight};line-height:1.5;\">{escape(line.strip())}</p>"
        )
    return _html_card("System Notes", "".join(html_lines), accent="#64748b")


def _deferred_cells(result: SignalResult) -> list[str]:
    return [
        result.symbol,
        result.rating,
        _score_label(result),
        result.conviction_level,
        _compact_summary(result.bull_case, 1),
        result.portfolio_reason,
    ]


def _watchlist_cells(result: SignalResult) -> list[str]:
    next_condition = result.trade_plan.trigger or "Wait for better alignment."
    why_not_now = result.portfolio_reason or _compact_summary(result.bear_case or result.risks, 1)
    return [result.symbol, result.rating, _score_label(result), next_condition, why_not_now]


def _trading_posture(market: MarketContext, approved_count: int) -> str:
    if market.label == MARKET_RISK_OFF:
        return "Defense first"
    if approved_count > 0:
        return "Selective execution"
    if market.label == MARKET_RISK_ON:
        return "Stay patient for cleaner entries"
    return "Neutral and patient"


def _summary_line(market: MarketContext, approved: list[SignalResult], deferred_count: int) -> str:
    if approved:
        leaders = ", ".join(item.symbol for item in approved[:2])
        return (
            f"The board is constructive enough to approve {len(approved)} trade plan(s), "
            f"led by {leaders}, while {deferred_count} candidate(s) remain on hold."
        )
    if market.label == MARKET_RISK_OFF:
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
        f"── {result.symbol} ──",
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
    data_warnings = dedupe([warning for result in results for warning in result.warnings])
    validation_warnings = dedupe(
        [warning for result in results for warning in result.validation_warnings]
    )
    heat_warnings = dedupe(
        [warning for result in results for warning in result.portfolio_warnings]
    )
    data_quality_notes = dedupe(
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
        lines.extend(["- portfolio notes:"] + [f"  - {item}" for item in dedupe(portfolio_notes)[:6]])
    if review_notes:
        lines.extend(["- decision review:"] + [f"  - {item}" for item in dedupe(review_notes)[:4]])
    return lines


def _compact_summary(items: list[str], limit: int = 2) -> str:
    filtered = [item for item in items if item]
    if not filtered:
        return "None."
    return " ; ".join(filtered[:limit])


def _score_label(result: SignalResult) -> str:
    if result.score >= 100 and result.raw_score > 100:
        return "100+"
    return str(result.score)

