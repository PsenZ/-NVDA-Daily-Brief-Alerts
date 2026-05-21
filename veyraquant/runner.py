from .config import AppConfig
from .data import DataClient
from .decision_manager import apply_portfolio_manager
from .emailer import send_email
from .market import build_market_context
from .memory import sync_decision_log
from .memory_review import brief_review_notes
from .models import SymbolData
from .positions import apply_position_context, load_positions
from .reporting import (
    compose_alert_email,
    compose_alert_email_html,
    compose_daily_report,
    compose_daily_report_html,
)
from .signals import analyze_symbol, assign_ranks, enforce_portfolio_heat
from .state import (
    already_sent_daily,
    mark_alert_sent,
    mark_daily_sent,
    read_state,
    should_send_alert,
    write_state,
)
from .timeutils import US_EASTERN_TZ, daily_report_due, is_regular_us_market_hours, now_sydney


def run(config: AppConfig | None = None) -> int:
    config = config or AppConfig.from_env()
    now_dt = now_sydney()
    now_dt_et = now_dt.astimezone(US_EASTERN_TZ)
    state = read_state(config.state_path)
    daily_due = config.force_daily_report or (
        daily_report_due(now_dt, config.send_hour, config.send_minute, config.send_window_minutes)
        and not already_sent_daily(state, now_dt)
    )
    alerts_due = (
        (config.entry_alerts_enabled or getattr(config, "risk_alerts_enabled", False))
        and is_regular_us_market_hours(now_dt_et)
    )
    if not daily_due and not alerts_due:
        print("Daily report skipped: before send threshold or already sent today.")
        print("Entry and risk alerts skipped: outside regular US market hours or disabled.")
        print("Nothing sent; state unchanged.")
        return 0

    client = DataClient(config)
    positions = load_positions(config.positions_path)
    market_histories = {symbol: client.fetch_market_daily(symbol) for symbol in config.market_symbols}
    market = build_market_context(market_histories)
    symbol_data_items = [client.fetch_symbol(symbol) for symbol in config.symbols]
    results, portfolio_notes = build_results(symbol_data_items, market, config, positions)
    review_notes = brief_review_notes(config.memory_log_path)

    sent_any = False
    changed = False
    daily_sent, daily_changed = maybe_send_daily_report(
        state, now_dt, results, market, portfolio_notes, config, review_notes
    )
    if daily_sent:
        sent_any = True
    if daily_changed:
        changed = True
    if maybe_send_entry_alerts(state, now_dt, results, config):
        sent_any = True
        changed = True

    if changed and not config.dry_run:
        write_state(config.state_path, state)
        print("State updated.")
    elif config.dry_run:
        print("DRY_RUN enabled; state unchanged.")
    elif sent_any:
        print("Send completed; state unchanged.")
    else:
        print("Nothing sent; state unchanged.")
    return 0


def build_results(symbol_data_items: list[SymbolData], market, config: AppConfig, positions=None):
    results = [
        analyze_symbol(
            item.symbol,
            item.daily,
            item.intraday,
            item.fundamentals,
            item.options,
            item.news,
            market,
            config,
            item.warnings,
        )
        for item in symbol_data_items
    ]
    ranked = assign_ranks(results)
    heat_adjusted = enforce_portfolio_heat(ranked, config.portfolio_heat_max_pct)
    reviewed, portfolio_notes = apply_portfolio_manager(heat_adjusted, market, config)
    return apply_position_context(reviewed, positions or {}), portfolio_notes


def maybe_send_daily_report(
    state,
    now_dt,
    results,
    market,
    portfolio_notes,
    config: AppConfig,
    review_notes=None,
) -> tuple[bool, bool]:
    if not config.force_daily_report and not daily_report_due(
        now_dt, config.send_hour, config.send_minute, config.send_window_minutes
    ):
        print("Daily report skipped: before send threshold.")
        return False, False
    if not config.force_daily_report and already_sent_daily(state, now_dt):
        print("Daily report skipped: already sent today.")
        return False, False

    subject, body = compose_daily_report(results, market, config, now_dt, portfolio_notes, review_notes)
    try:
        html_body = compose_daily_report_html(results, market, config, now_dt, portfolio_notes, review_notes)
    except Exception:
        html_body = None
    if config.dry_run:
        print(subject)
        print(body)
        return False, False

    _send_email(config.smtp, subject, body, html_body)
    sync_decision_log(
        config.memory_log_path,
        now_dt,
        results,
        config.decision_memory_holding_days,
    )
    if config.force_daily_report:
        print("Daily report force-sent without updating daily state.")
        return True, False

    mark_daily_sent(state, now_dt)
    print("Daily report sent.")
    return True, True


def maybe_send_entry_alerts(state, now_dt, results, config: AppConfig) -> bool:
    if not config.entry_alerts_enabled and not getattr(config, "risk_alerts_enabled", False):
        print("Entry and risk alerts disabled.")
        return False
    now_dt_et = now_dt.astimezone(US_EASTERN_TZ)
    if not is_regular_us_market_hours(now_dt_et):
        print("Entry and risk alerts skipped: outside regular US market hours.")
        return False

    sent_any = False
    for result in results:
        if not _alert_channel(result, config):
            continue
        should_send, reason = should_send_alert(
            state,
            result.symbol,
            result.alert_kind,
            now_dt,
            config.alert_cooldown_hours,
            getattr(result, "signal_hash", None),
        )
        if not should_send:
            print(f"Alert skipped due to cooldown: {result.symbol} {result.alert_kind}")
            continue

        subject, body = compose_alert_email(result, now_dt)
        try:
            html_body = compose_alert_email_html(result, now_dt)
        except Exception:
            html_body = None
        if config.dry_run:
            print(subject)
            print(body)
            continue

        _send_email(config.smtp, subject, body, html_body)
        mark_alert_sent(
            state,
            result.symbol,
            result.alert_kind,
            now_dt,
            {
                "score": result.score,
                "signal_hash": result.signal_hash,
                "plan": {
                    "entry_zone": result.entry_zone,
                    "stop": result.stop,
                    "targets": result.targets,
                    "position_pct": result.position_pct,
                    "max_loss_pct": result.max_loss_pct,
                },
                "reason": reason,
                "channel": _alert_channel(result, config),
            },
        )
        sent_any = True
        print(f"Alert sent: {result.symbol} {result.alert_kind} ({reason})")

    if not sent_any:
        print("No alert sent.")
    return sent_any


def _should_alert(result, config: AppConfig) -> bool:
    return bool(_alert_channel(result, config))


def _alert_channel(result, config: AppConfig) -> str | None:
    if result.action == "RISK_REDUCE" and getattr(config, "risk_alerts_enabled", False):
        return "risk"
    if not getattr(result, "is_actionable", False):
        return None
    if result.alert_kind in {"breakout_entry", "pullback_add"}:
        if getattr(config, "entry_alerts_enabled", True) and result.score >= config.alert_score_threshold:
            return "entry"
    return None


def _send_email(smtp, subject, body, html_body=None) -> None:
    try:
        send_email(smtp, subject, body, html_body)
    except TypeError as exc:
        try:
            send_email(smtp, subject, body)
        except TypeError:
            raise exc
