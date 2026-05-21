from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass
class FundamentalsData:
    market_cap: Any = None
    trailing_pe: Any = None
    forward_pe: Any = None
    ps: Any = None
    profit_margin: Any = None
    roe: Any = None
    revenue_growth: Any = None
    earnings_growth: Any = None
    fifty_two_week_high: Any = None
    fifty_two_week_low: Any = None
    target_mean_price: Any = None
    recommendation_key: Any = None
    current_price: Any = None


@dataclass
class OptionsData:
    expiration: str
    put_call_oi: Optional[float]
    put_call_vol: Optional[float]
    iv_mid: Optional[float]


@dataclass
class NewsBundle:
    news: list[dict[str, Any]]
    social: list[dict[str, Any]]
    social_sentiment: dict[str, Any]


@dataclass
class SymbolData:
    symbol: str
    daily: Optional[pd.DataFrame]
    intraday: Optional[pd.DataFrame]
    fundamentals: FundamentalsData
    options: Optional[OptionsData]
    news: NewsBundle
    warnings: list[str] = field(default_factory=list)


@dataclass
class MarketContext:
    label: str
    score: float
    reasons: list[str]
    risks: list[str]
    snapshots: dict[str, dict[str, Any]]


@dataclass
class TechSnapshot:
    values: dict[str, float]


@dataclass
class TradePlan:
    entry_zone: str
    stop: str
    targets: str
    position_pct: float
    max_loss_pct: float
    rr: float
    trigger: str
    cancel: str
    account_equity: Optional[float] = None
    position_value: Optional[float] = None


@dataclass
class SignalResult:
    rank: int
    symbol: str
    signal_type: str
    score: int
    market_regime: str
    entry_zone: str
    stop: str
    targets: str
    position_pct: float
    max_loss_pct: float
    reasons: list[str]
    risks: list[str]
    contributions: dict[str, float]
    trade_plan: TradePlan
    alert_kind: str
    signal_hash: str
    last_price: Optional[float]
    raw_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    setup_type: str = ""
    action: str = "WAIT"
    is_actionable: bool = False
    suppressed_by: list[str] = field(default_factory=list)
    plan_kind: str = "wait"
    rating: str = "Hold"
    bull_case: list[str] = field(default_factory=list)
    bear_case: list[str] = field(default_factory=list)
    market_evidence: list[str] = field(default_factory=list)
    conviction_level: str = "low"
    decision_balance: str = "mixed"
    validation_warnings: list[str] = field(default_factory=list)
    portfolio_warnings: list[str] = field(default_factory=list)
    portfolio_decision: str = "watchlist"
    portfolio_reason: str = ""
    has_open_position: bool = False
    position_context: str = "No open position."
    suggested_posture: str = "monitor-only"
    approval_rank_score: float = 0.0
    sector_bucket: str = ""
    defer_reason_code: str = ""
    approval_reason_code: str = ""
    sector_risk_after: float = 0.0
    sector_position_after: float = 0.0
