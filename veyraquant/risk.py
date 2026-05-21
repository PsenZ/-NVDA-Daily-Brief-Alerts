from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PositionSizing:
    position_pct: float
    max_loss_pct: float
    position_value: Optional[float]


def position_size_pct(
    entry: float,
    stop: float,
    risk_per_trade_pct: float,
    max_position_pct: float,
    account_equity: Optional[float] = None,
) -> PositionSizing:
    if entry <= 0 or stop <= 0 or stop >= entry:
        return PositionSizing(0.0, 0.0, None)

    stop_distance_pct = (entry - stop) / entry * 100
    raw_position_pct = risk_per_trade_pct / stop_distance_pct * 100
    position_pct = max(0.0, min(max_position_pct, raw_position_pct))
    max_loss_pct = position_pct * stop_distance_pct / 100
    position_value = None if account_equity is None else account_equity * position_pct / 100
    return PositionSizing(round(position_pct, 2), round(max_loss_pct, 2), position_value)


def portfolio_heat_cap(position_pct: float, max_loss_pct: float, heat_left_pct: float) -> tuple[float, float]:
    if max_loss_pct <= heat_left_pct or max_loss_pct <= 0:
        return round(position_pct, 2), round(max_loss_pct, 2)
    ratio = heat_left_pct / max_loss_pct
    return round(position_pct * ratio, 2), round(heat_left_pct, 2)


def budget_exceeded(current_pct: float, addition_pct: float, limit_pct: float | None) -> bool:
    if limit_pct is None or limit_pct <= 0:
        return False
    return current_pct + addition_pct > limit_pct + 1e-9


def budget_after(current_pct: float, addition_pct: float) -> float:
    return round(current_pct + addition_pct, 4)
