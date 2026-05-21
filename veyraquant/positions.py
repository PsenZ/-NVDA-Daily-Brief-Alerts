import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: float | None = None
    position_pct: float | None = None
    cost_basis: float | None = None
    opened_at: str | None = None
    notes: str = ""


def load_positions(path: str) -> dict[str, Position]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

    rows = payload.get("positions", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}

    positions: dict[str, Position] = {}
    for row in rows:
        position = _parse_position(row)
        if position is not None:
            positions[position.symbol] = position
    return positions


def apply_position_context(results, positions: dict[str, Position]):
    for result in results:
        position = positions.get(result.symbol.upper())
        if position is None:
            result.has_open_position = False
            result.position_context = "No open position."
            result.suggested_posture = "monitor-only"
            if result.action == "RISK_REDUCE":
                result.portfolio_reason = "Monitor-only risk signal because no open position is recorded."
            continue

        result.has_open_position = True
        result.position_context = _format_position_context(position)
        if result.action == "RISK_REDUCE":
            result.suggested_posture = "de-risk" if _position_size(position) >= 5 else "trim"
            result.portfolio_reason = (
                f"{result.suggested_posture} recorded exposure; avoid adding fresh risk."
            )
        else:
            result.suggested_posture = "hold-context"
    return results


def _parse_position(row: Any) -> Position | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol:
        return None
    shares = _float_or_none(row.get("shares"))
    position_pct = _float_or_none(row.get("position_pct"))
    if shares is None and position_pct is None:
        return None
    return Position(
        symbol=symbol,
        shares=shares,
        position_pct=position_pct,
        cost_basis=_float_or_none(row.get("cost_basis")),
        opened_at=str(row.get("opened_at")) if row.get("opened_at") else None,
        notes=str(row.get("notes", "")),
    )


def _format_position_context(position: Position) -> str:
    parts = ["open position"]
    if position.position_pct is not None:
        parts.append(f"{position.position_pct:.2f}%")
    if position.shares is not None:
        parts.append(f"{position.shares:g} shares")
    if position.cost_basis is not None:
        parts.append(f"cost ${position.cost_basis:.2f}")
    if position.opened_at:
        parts.append(f"opened {position.opened_at}")
    return ", ".join(parts)


def _position_size(position: Position) -> float:
    if position.position_pct is not None:
        return position.position_pct
    return 0.0


def _float_or_none(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except Exception:
        return None
