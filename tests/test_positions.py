import json
from types import SimpleNamespace

from veyraquant.positions import apply_position_context, load_positions


def test_load_positions_missing_file_returns_empty(tmp_path):
    assert load_positions(str(tmp_path / "missing.json")) == {}


def test_load_positions_accepts_positions_wrapper(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "symbol": "nvda",
                        "position_pct": 7.5,
                        "cost_basis": 900.25,
                        "opened_at": "2026-04-01",
                    },
                    {"symbol": "TSLA"},
                ]
            }
        ),
        encoding="utf-8",
    )

    positions = load_positions(str(path))

    assert set(positions) == {"NVDA"}
    assert positions["NVDA"].position_pct == 7.5
    assert positions["NVDA"].cost_basis == 900.25


def test_risk_reduce_with_open_position_gets_executable_context(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps([{"symbol": "TSLA", "shares": 12, "position_pct": 6.0, "cost_basis": 210.0}]),
        encoding="utf-8",
    )
    result = SimpleNamespace(symbol="TSLA", action="RISK_REDUCE", portfolio_reason="")

    apply_position_context([result], load_positions(str(path)))

    assert result.has_open_position is True
    assert "6.00%" in result.position_context
    assert "12 shares" in result.position_context
    assert "cost $210.00" in result.position_context
    assert result.suggested_posture == "de-risk"
    assert "recorded exposure" in result.portfolio_reason


def test_risk_reduce_without_position_is_monitor_only():
    result = SimpleNamespace(symbol="AMD", action="RISK_REDUCE", portfolio_reason="")

    apply_position_context([result], {})

    assert result.has_open_position is False
    assert result.position_context == "No open position."
    assert result.suggested_posture == "monitor-only"
    assert "Monitor-only" in result.portfolio_reason
