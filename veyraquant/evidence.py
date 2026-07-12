"""Structured evidence: every score point and every veto is traceable.

EvidenceItem is the audit unit. The scoring layer routes all of its
reason/risk strings through an EvidenceCollector so the human-readable
lists stay byte-identical to the legacy output while a parallel
machine-readable trail records code, component, points, source and
measured value. Gate vetoes (suppressed_by codes) map to gate evidence
via a registry, so every rejection carries a machine-readable reason.

Invariant (tested): for each contribution component, the sum of evidence
points equals the contribution value - every point is accounted for.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EvidenceItem:
    code: str
    text: str
    polarity: str          # "reason" | "risk" | "info"
    component: str         # contribution bucket, or "gate"
    points: Optional[float] = None
    source: str = "technical"
    value: Any = None
    confidence: str = "rule"
    timestamp: Optional[str] = None  # stamped at export time with the run time

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "text": self.text,
            "polarity": self.polarity,
            "component": self.component,
            "points": self.points,
            "source": self.source,
            "value": self.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class EvidenceCollector:
    """Single writer for reasons/risks text AND structured evidence, so
    the two views cannot drift apart."""

    def __init__(self) -> None:
        self.items: list[EvidenceItem] = []
        self._reasons: list[str] = []
        self._risks: list[str] = []

    def reason(self, code: str, text: str, component: str, points: float | None = None,
               source: str = "technical", value: Any = None) -> None:
        self._reasons.append(text)
        self.items.append(EvidenceItem(code, text, "reason", component, points, source, value))

    def risk(self, code: str, text: str, component: str, points: float | None = None,
             source: str = "technical", value: Any = None) -> None:
        self._risks.append(text)
        self.items.append(EvidenceItem(code, text, "risk", component, points, source, value))

    def info(self, code: str, text: str, component: str, points: float | None = None,
             source: str = "technical", value: Any = None) -> None:
        # Carries points without adding narrative to the report.
        self.items.append(EvidenceItem(code, text, "info", component, points, source, value))

    @property
    def reasons(self) -> list[str]:
        return self._reasons

    @property
    def risks(self) -> list[str]:
        return self._risks


# Machine-readable gate codes -> (source, standard description).
# The codes are exactly the strings used in SignalResult.suppressed_by.
GATE_REGISTRY: dict[str, tuple[str, str]] = {
    "insufficient_daily_data": ("data_quality", "Daily history shorter than the instrument's minimum."),
    "data_quality_gate": ("data_quality", "Price data too stale for an actionable signal."),
    "market_risk_off": ("market", "Market regime is risk-off and the score lacks override margin."),
    "negative_news_veto": ("news", "Negative headline/social sentiment vetoed the entry."),
    "earnings_blackout": ("fundamental", "Earnings inside the blackout window."),
    "leveraged_product_policy": ("policy", "Leveraged/inverse product excluded from fresh entries."),
    "insufficient_liquidity": ("policy", "Average dollar volume below the liquidity floor."),
    "rr_below_min": ("validation", "Preview reward/risk below the configured minimum."),
    "trade_plan_validation_failed": ("validation", "Trade plan failed hard validation."),
}


def gate_evidence(code: str, text: str | None = None) -> EvidenceItem:
    source, description = GATE_REGISTRY.get(code, ("policy", "Suppressed by policy gate."))
    return EvidenceItem(
        code=code.upper(),
        text=text or description,
        polarity="risk",
        component="gate",
        points=None,
        source=source,
    )


# Every code the scoring layer emits; tests verify emissions stay inside
# this registry so new evidence cannot be added anonymously.
SCORING_CODES = {
    "TREND_MA_STACK", "TREND_ABOVE_SMA20_50", "TREND_ABOVE_SMA20_ONLY",
    "TREND_BELOW_SMA20", "TREND_ABOVE_SMA200", "TREND_NEAR_55D_HIGH",
    "MOM_MACD_EXPANDING", "MOM_MACD_ABOVE_SIGNAL", "MOM_MACD_BELOW_SIGNAL",
    "MOM_RSI_HEALTHY", "MOM_RSI_OVERHEATED", "MOM_RSI_WEAK", "MOM_ADX_TREND",
    "RS_BASELINE", "RS_SPREAD_OUTPERFORM", "RS_SPREAD_LAG", "RS_SPREAD_NEUTRAL",
    "VOL_SURGE_5D", "VOL_ABOVE_20D", "VOL_MODEST", "VOL_LIGHT_PULLBACK", "VOL_WEAK",
    "VOLOPT_BASELINE", "VOLOPT_ATR_ELEVATED", "OPT_IV_HIGH", "OPT_IV_LOW",
    "OPT_PC_BEARISH", "OPT_PC_SUPPORTIVE",
    "NEWS_SENT_POSITIVE", "NEWS_SENT_NEGATIVE", "NEWS_COVERAGE",
    "DISC_EXTENDED_MA5", "DISC_NEAR_MA5", "DISC_NEAR_MA10",
    "SECTOR_BENCH_STRONG", "SECTOR_QQQ_TAILWIND",
    "FUND_RECO_BUY", "FUND_RECO_SELL", "FUND_REVENUE_NEGATIVE",
    "MARKET_ENV_SCORE", "MARKET_RISK_ON_NOTE", "MARKET_RISK_OFF_NOTE",
    "BASE_SCORE",
}
KNOWN_CODES = SCORING_CODES | {code.upper() for code in GATE_REGISTRY}
