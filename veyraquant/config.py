import os
import json
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_SECTOR_MAP = {
    "NVDA": "semiconductor",
    "AMD": "semiconductor",
    "MU": "semiconductor",
    "SMH": "semiconductor",
    "QQQ": "mega_growth",
    "AAPL": "mega_growth",
    "MSFT": "mega_growth",
    "TSLA": "auto_growth",
}
DEFAULT_SECTOR_RISK_LIMITS = {
    "semiconductor": 1.2,
    "mega_growth": 1.5,
    "auto_growth": 0.8,
    "general": 1.0,
}
DEFAULT_SECTOR_POSITION_LIMITS = {
    "semiconductor": 20.0,
    "mega_growth": 25.0,
    "auto_growth": 10.0,
    "general": 10.0,
}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _json_dict_env(name: str, default: dict) -> dict:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return dict(default)
    try:
        payload = json.loads(value)
    except Exception:
        return dict(default)
    if not isinstance(payload, dict):
        return dict(default)
    return payload


def _str_dict_env(name: str, default: dict[str, str]) -> dict[str, str]:
    payload = _json_dict_env(name, default)
    normalized: dict[str, str] = {}
    for key, value in payload.items():
        symbol = str(key).strip().upper()
        sector = str(value).strip()
        if symbol and sector:
            normalized[symbol] = sector
    return normalized or dict(default)


def _float_dict_env(name: str, default: dict[str, float]) -> dict[str, float]:
    payload = _json_dict_env(name, default)
    normalized: dict[str, float] = {}
    for key, value in payload.items():
        sector = str(key).strip()
        try:
            limit = float(value)
        except Exception:
            continue
        if sector and limit >= 0:
            normalized[sector] = limit
    return normalized or dict(default)


def _symbols_from_env() -> list[str]:
    raw = os.getenv("SYMBOLS") or os.getenv("SYMBOL") or "NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH"
    symbols = [part.strip().upper() for part in raw.split(",") if part.strip()]
    return symbols or ["NVDA"]


@dataclass(frozen=True)
class StrategyConfig:
    breakout_score_offset: int = 0
    breakout_high20_ratio: float = 0.995
    breakout_vol_ratio_5_min: float = 2.0
    breakout_close_position_min: float = 0.7
    breakout_max_dist_ma5_pct: float = 5.0
    intraday_breakout_high13_ratio: float = 0.998
    intraday_breakout_vol_ratio_min: float = 2.0
    pullback_score_offset: int = -5
    pullback_ma5_distance_pct: float = 1.0
    pullback_ma10_distance_pct: float = 2.0
    pullback_vol_ratio_5_max: float = 0.7
    pullback_rsi_min: float = 42.0
    pullback_rsi_max: float = 62.0
    hold_watch_score_min: int = 55
    risk_reduce_score_max: int = 40
    risk_reduce_rsi_overheat: float = 74.0
    # Scoring judgment thresholds (score_components). Weights stay in code for now.
    score_base: float = 35.0
    score_rsi_healthy_min: float = 45.0
    score_rsi_healthy_max: float = 68.0
    score_rsi_overheat: float = 72.0
    score_rsi_weak: float = 40.0
    score_adx_trend_min: float = 25.0
    score_vol_ratio_5_strong: float = 2.0
    score_vol_ratio_strong: float = 1.5
    score_vol_ratio_moderate: float = 1.1
    score_vol_ratio_light: float = 0.7
    score_dist_ma5_extended_pct: float = 5.0


def _load_strategy_config(path: str) -> StrategyConfig:
    if not path or not os.path.exists(path):
        return StrategyConfig()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return StrategyConfig()
    if not isinstance(payload, dict):
        return StrategyConfig()
    allowed = set(StrategyConfig.__dataclass_fields__)
    values = {key: value for key, value in payload.items() if key in allowed}
    try:
        return StrategyConfig(**values)
    except Exception:
        return StrategyConfig()


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    from_email: Optional[str]
    to_email: Optional[str]


@dataclass(frozen=True)
class AppConfig:
    symbols: list[str]
    market_symbols: list[str]
    send_hour: int
    send_minute: int
    send_window_minutes: int
    state_path: str
    cache_dir: str
    subject_prefix: str
    entry_alerts_enabled: bool
    alert_cooldown_hours: int
    alert_score_threshold: int
    social_sentiment_threshold: float
    intraday_interval: str
    account_equity: Optional[float]
    risk_per_trade_pct: float
    max_position_pct: float
    portfolio_heat_max_pct: float
    atr_stop_multiplier: float
    min_rr: float
    force_daily_report: bool
    dry_run: bool
    smtp: SmtpConfig
    risk_alerts_enabled: bool = False
    max_entry_zone_width_warn_pct: float = 3.0
    max_entry_zone_width_reject_pct: float = 6.0
    memory_log_path: str = os.path.join("memory", "decision_log.jsonl")
    decision_memory_holding_days: int = 5
    positions_path: str = os.path.join("state", "positions.json")
    strategy_config_path: str = os.path.join("strategies", "default.json")
    strategy: StrategyConfig = StrategyConfig()
    sector_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SECTOR_MAP))
    sector_risk_limits: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SECTOR_RISK_LIMITS)
    )
    sector_position_limits: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SECTOR_POSITION_LIMITS)
    )
    max_approved_actions_risk_on: int = 3
    max_approved_actions_neutral: int = 2
    max_approved_actions_risk_off: int = 0
    price_cache_actionable_max_age_hours: float = 24.0
    price_cache_invalid_max_age_hours: float = 72.0
    data_workers: int = 4

    @classmethod
    def from_env(cls) -> "AppConfig":
        symbols = _symbols_from_env()
        market_symbols = [
            part.strip().upper()
            for part in os.getenv("MARKET_SYMBOLS", "SPY,QQQ,SMH,^VIX").split(",")
            if part.strip()
        ]
        account_equity_raw = os.getenv("ACCOUNT_EQUITY")
        account_equity = float(account_equity_raw) if account_equity_raw else None
        subject_default = (
            f"{symbols[0]} 每日简报" if len(symbols) == 1 else "VeyraQuant 量化简报"
        )

        strategy_config_path = os.getenv(
            "STRATEGY_CONFIG_PATH", os.path.join("strategies", "default.json")
        )

        return cls(
            symbols=symbols,
            market_symbols=market_symbols,
            send_hour=_int_env("SEND_HOUR", 7),
            send_minute=_int_env("SEND_MINUTE", 30),
            send_window_minutes=_int_env("SEND_WINDOW_MINUTES", 30),
            state_path=os.getenv("STATE_PATH", os.path.join("state", "last_sent.json")),
            cache_dir=os.getenv("CACHE_DIR", os.path.join(".cache", "veyraquant")),
            subject_prefix=os.getenv("SUBJECT_PREFIX", subject_default),
            entry_alerts_enabled=_bool_env("ENABLE_ENTRY_ALERTS", True),
            risk_alerts_enabled=_bool_env("ENABLE_RISK_ALERTS", False),
            alert_cooldown_hours=_int_env("ALERT_COOLDOWN_HOURS", 12),
            alert_score_threshold=_int_env("ALERT_SCORE_THRESHOLD", 65),
            social_sentiment_threshold=_float_env("SOCIAL_SENTIMENT_THRESHOLD", 0.15),
            intraday_interval=os.getenv("INTRADAY_INTERVAL", "30m"),
            account_equity=account_equity,
            risk_per_trade_pct=_float_env("RISK_PER_TRADE_PCT", 0.5),
            max_position_pct=_float_env("MAX_POSITION_PCT", 10.0),
            portfolio_heat_max_pct=_float_env("PORTFOLIO_HEAT_MAX_PCT", 3.0),
            atr_stop_multiplier=_float_env("ATR_STOP_MULTIPLIER", 2.0),
            min_rr=_float_env("MIN_RR", 1.5),
            force_daily_report=_bool_env("FORCE_DAILY_REPORT", False),
            dry_run=_bool_env("DRY_RUN", False),
            smtp=SmtpConfig(
                host=os.getenv("SMTP_HOST", "smtp.mail.yahoo.com"),
                port=_int_env("SMTP_PORT", 465),
                user=os.getenv("SMTP_USER"),
                password=os.getenv("SMTP_APP_PASSWORD"),
                from_email=os.getenv("FROM_EMAIL"),
                to_email=os.getenv("TO_EMAIL"),
            ),
            max_entry_zone_width_warn_pct=_float_env("MAX_ENTRY_ZONE_WIDTH_WARN_PCT", 3.0),
            max_entry_zone_width_reject_pct=_float_env("MAX_ENTRY_ZONE_WIDTH_REJECT_PCT", 6.0),
            memory_log_path=os.getenv(
                "MEMORY_LOG_PATH", os.path.join("memory", "decision_log.jsonl")
            ),
            decision_memory_holding_days=_int_env("DECISION_MEMORY_HOLDING_DAYS", 5),
            positions_path=os.getenv("POSITIONS_PATH", os.path.join("state", "positions.json")),
            strategy_config_path=strategy_config_path,
            strategy=_load_strategy_config(strategy_config_path),
            sector_map=_str_dict_env("SECTOR_MAP_JSON", DEFAULT_SECTOR_MAP),
            sector_risk_limits=_float_dict_env(
                "SECTOR_RISK_LIMITS_JSON", DEFAULT_SECTOR_RISK_LIMITS
            ),
            sector_position_limits=_float_dict_env(
                "SECTOR_POSITION_LIMITS_JSON", DEFAULT_SECTOR_POSITION_LIMITS
            ),
            max_approved_actions_risk_on=_int_env("MAX_APPROVED_ACTIONS_RISK_ON", 3),
            max_approved_actions_neutral=_int_env("MAX_APPROVED_ACTIONS_NEUTRAL", 2),
            max_approved_actions_risk_off=_int_env("MAX_APPROVED_ACTIONS_RISK_OFF", 0),
            price_cache_actionable_max_age_hours=_float_env(
                "PRICE_CACHE_ACTIONABLE_MAX_AGE_HOURS", 24.0
            ),
            price_cache_invalid_max_age_hours=_float_env(
                "PRICE_CACHE_INVALID_MAX_AGE_HOURS", 72.0
            ),
            data_workers=_int_env("DATA_WORKERS", 4),
        )
