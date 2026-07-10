import logging
from concurrent.futures import ThreadPoolExecutor

from .config import AppConfig
from .data import DataClient
from .decision_manager import apply_portfolio_manager
from .emailer import send_email
from .market import build_market_context
from .memory import sync_decision_log
from .memory_review import brief_review_notes
from .models import DataQuality, FundamentalsData, NewsBundle, SymbolData
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
from .timeutils import US_EASTERN_TZ, daily_report_due, is_us_market_weekday, now_sydney


logger = logging.getLogger(__name__)


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
        and is_us_market_weekday(now_dt_et)
    )
    if not daily_due and not alerts_due:
        logger.info("Daily report skipped: before send threshold or already sent today.")
        logger.info("Entry and risk alerts skipped: disabled or US market weekend.")
        logger.info("Nothing sent; state unchanged.")
        return 0

    client = DataClient(config)
    positions = load_positions(config.positions_path)
    market_histories = _fetch_market_histories(client, config)
    market = build_market_context(market_histories)
    symbol_data_items = _fetch_symbol_data(client, config)
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
        logger.info("State updated.")
    elif config.dry_run:
        logger.info("DRY_RUN enabled; state unchanged.")
    elif sent_any:
        logger.info("Send completed; state unchanged.")
    else:
        logger.info("Nothing sent; state unchanged.")
    return 0


def _data_workers(config: AppConfig, item_count: int) -> int:
    requested = getattr(config, "data_workers", 4)
    try:
        requested = int(requested)
    except Exception:
        requested = 4
    return max(1, min(requested, max(1, item_count)))


def _fetch_market_histories(client: DataClient, config: AppConfig) -> dict:
    symbols = list(config.market_symbols)
    if not symbols:
        return {}
    workers = _data_workers(config, len(symbols))
    if workers == 1:
        histories = [client.fetch_market_daily(symbol) for symbol in symbols]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            histories = list(pool.map(client.fetch_market_daily, symbols))
    return dict(zip(symbols, histories))


def _fetch_symbol_data(client: DataClient, config: AppConfig) -> list[SymbolData]:
    symbols = list(config.symbols)
    if not symbols:
        return []

    def fetch(symbol: str) -> SymbolData:
        try:
            return client.fetch_symbol(symbol)
        except Exception:
            logger.warning("%s symbol fetch failed; skipping with empty data.", symbol, exc_info=True)
            quality = DataQuality(data_quality_level="LOW", actionable_allowed=False)
            quality.reasons.append("symbol data fetch raised an unexpected error")
            return SymbolData(
                symbol=symbol,
                daily=None,
                intraday=None,
                fundamentals=FundamentalsData(),
                options=None,
                news=NewsBundle([], [], {"score": 0.0, "label": "中性", "sample_size": 0}),
                warnings=[f"{symbol} data fetch failed unexpectedly."],
                data_quality=quality,
            )

    workers = _data_workers(config, len(symbols))
    if workers == 1:
        return [fetch(symbol) for symbol in symbols]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fetch, symbols))


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
            item.data_quality,
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
        logger.info("Daily report skipped: before send threshold.")
        return False, False
    if not config.force_daily_report and already_sent_daily(state, now_dt):
        logger.info("Daily report skipped: already sent today.")
        return False, False

    subject, body = compose_daily_report(results, market, config, now_dt, portfolio_notes, review_notes)
    try:
        html_body = compose_daily_report_html(results, market, config, now_dt, portfolio_notes, review_notes)
    except Exception:
        logger.warning("HTML daily report render failed; falling back to plain text.", exc_info=True)
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
        logger.info("Daily report force-sent without updating daily state.")
        return True, False

    mark_daily_sent(state, now_dt)
    logger.info("Daily report sent.")
    return True, True


def maybe_send_entry_alerts(state, now_dt, results, config: AppConfig) -> bool:
    if not config.entry_alerts_enabled and not getattr(config, "risk_alerts_enabled", False):
        logger.info("Entry and risk alerts disabled.")
        return False
    now_dt_et = now_dt.astimezone(US_EASTERN_TZ)
    if not is_us_market_weekday(now_dt_et):
        logger.info("Entry and risk alerts skipped: US market weekend.")
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
            logger.info("Alert skipped due to cooldown: %s %s", result.symbol, result.alert_kind)
            continue

        subject, body = compose_alert_email(result, now_dt)
        try:
            html_body = compose_alert_email_html(result, now_dt)
        except Exception:
            logger.warning("HTML alert render failed; falling back to plain text.", exc_info=True)
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
        logger.info("Alert sent: %s %s (%s)", result.symbol, result.alert_kind, reason)

    if not sent_any:
        logger.info("No alert sent.")
    return sent_any


def _alert_channel(result, config: AppConfig) -> str | None:
    if result.action == "RISK_REDUCE" and getattr(config, "risk_alerts_enabled", False):
        return "risk"
    if not getattr(result, "is_actionable", False):
        return None
    if result.alert_kind in {"breakout_entry", "pullback_add"}:
        data_quality = getattr(result, "data_quality", None)
        if data_quality is not None and not getattr(data_quality, "intraday_alert_allowed", True):
            return None
        if getattr(config, "entry_alerts_enabled", True) and result.score >= config.alert_score_threshold:
            return "entry"
    return None


def _send_email(smtp, subject, body, html_body=None) -> None:
    send_email(smtp, subject, body, html_body)
