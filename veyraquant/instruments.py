"""US instrument registry: capability and policy metadata per ticker.

Scope is deliberately US-only (per roadmap R2): asset-type classification,
sector benchmark, options/fundamentals capability, leveraged/inverse/ADR
flags, history sufficiency and a liquidity floor. Resolution order:

1. explicit entry (built-in defaults merged with config/instruments.json)
2. inference from the ticker shape (-USD -> crypto, ^ -> index)
3. plain-stock defaults

Unknown tickers therefore work out of the box with conservative policy.
"""
import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Any, Optional


logger = logging.getLogger(__name__)

DEFAULT_MIN_HISTORY_BARS = 60
# ~$5M average daily dollar volume: below this, fills on a swing-size
# position move the market and the backtest cost model is fiction.
DEFAULT_MIN_AVG_DOLLAR_VOLUME = 5_000_000.0


@dataclass(frozen=True)
class InstrumentProfile:
    symbol: str
    asset_type: str = "stock"  # stock | etf | index | crypto
    sector: str = "general"
    sector_benchmark: Optional[str] = None
    qqq_sensitive: bool = False
    has_options: bool = True
    has_fundamentals: bool = True
    is_leveraged: bool = False
    is_inverse: bool = False
    is_adr: bool = False
    min_history_bars: int = DEFAULT_MIN_HISTORY_BARS
    min_avg_dollar_volume: Optional[float] = DEFAULT_MIN_AVG_DOLLAR_VOLUME


# Built-in entries for the default watchlist (chosen to reproduce the
# pre-registry scoring behavior exactly) plus common leveraged products.
BUILTIN: dict[str, dict[str, Any]] = {
    "NVDA": {"sector": "semiconductor", "sector_benchmark": "SMH", "qqq_sensitive": True},
    "AMD": {"sector": "semiconductor", "sector_benchmark": "SMH"},
    "MU": {"sector": "semiconductor", "sector_benchmark": "SMH"},
    "SMH": {"asset_type": "etf", "sector": "semiconductor", "sector_benchmark": "SMH",
            "has_fundamentals": False},
    "QQQ": {"asset_type": "etf", "sector": "mega_growth", "qqq_sensitive": True,
            "has_fundamentals": False},
    "SPY": {"asset_type": "etf", "sector": "broad_market", "has_fundamentals": False},
    "AAPL": {"sector": "mega_growth", "qqq_sensitive": True},
    "MSFT": {"sector": "mega_growth", "qqq_sensitive": True},
    "TSLA": {"sector": "auto_growth", "qqq_sensitive": True},
    "JPM": {"sector": "financials", "sector_benchmark": "XLF"},
    "XOM": {"sector": "energy", "sector_benchmark": "XLE"},
    "META": {"sector": "communication_services", "sector_benchmark": "XLC",
             "qqq_sensitive": True},
    "XLF": {"asset_type": "etf", "sector": "financials", "has_fundamentals": False},
    "XLE": {"asset_type": "etf", "sector": "energy", "has_fundamentals": False},
    "XLC": {"asset_type": "etf", "sector": "communication_services",
            "has_fundamentals": False},
    # Leveraged / inverse products: identified so policy can refuse them.
    "TQQQ": {"asset_type": "etf", "is_leveraged": True, "has_fundamentals": False},
    "SQQQ": {"asset_type": "etf", "is_leveraged": True, "is_inverse": True,
             "has_fundamentals": False},
    "SOXL": {"asset_type": "etf", "is_leveraged": True, "has_fundamentals": False},
    "SOXS": {"asset_type": "etf", "is_leveraged": True, "is_inverse": True,
             "has_fundamentals": False},
    "UPRO": {"asset_type": "etf", "is_leveraged": True, "has_fundamentals": False},
    "SPXU": {"asset_type": "etf", "is_leveraged": True, "is_inverse": True,
             "has_fundamentals": False},
    "UVXY": {"asset_type": "etf", "is_leveraged": True, "has_fundamentals": False},
    "SH": {"asset_type": "etf", "is_inverse": True, "has_fundamentals": False},
}

_ALLOWED_FIELDS = set(InstrumentProfile.__dataclass_fields__) - {"symbol"}


def load_registry(path: str = "") -> dict[str, dict[str, Any]]:
    """Built-ins merged with (and overridden by) config/instruments.json."""
    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTIN.items()}
    if not path or not os.path.exists(path):
        return merged
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        logger.warning("Unreadable instruments file %s; using built-ins.", path, exc_info=True)
        return merged
    if not isinstance(payload, dict):
        return merged
    for raw_symbol, fields in payload.items():
        if not isinstance(fields, dict):
            continue
        symbol = str(raw_symbol).strip().upper()
        entry = merged.setdefault(symbol, {})
        entry.update({k: v for k, v in fields.items() if k in _ALLOWED_FIELDS})
    return merged


def resolve_profile(symbol: str, registry: dict[str, dict[str, Any]] | None = None) -> InstrumentProfile:
    symbol = symbol.strip().upper()
    registry = registry if registry is not None else BUILTIN
    base = _inferred_defaults(symbol)
    entry = registry.get(symbol)
    if not entry:
        return base
    fields = {k: v for k, v in entry.items() if k in _ALLOWED_FIELDS}
    try:
        return replace(base, **fields)
    except Exception:
        logger.warning("Invalid instrument entry for %s; using inferred defaults.", symbol)
        return base


def default_profile(symbol: str) -> InstrumentProfile:
    """Profile without any config file - built-ins + inference only."""
    return resolve_profile(symbol, BUILTIN)


def _inferred_defaults(symbol: str) -> InstrumentProfile:
    if symbol.endswith("-USD"):
        return InstrumentProfile(
            symbol=symbol,
            asset_type="crypto",
            sector="crypto",
            has_options=False,
            has_fundamentals=False,
            min_avg_dollar_volume=None,
        )
    if symbol.startswith("^"):
        return InstrumentProfile(
            symbol=symbol,
            asset_type="index",
            sector="index",
            has_options=False,
            has_fundamentals=False,
            min_avg_dollar_volume=None,
        )
    return InstrumentProfile(symbol=symbol)
