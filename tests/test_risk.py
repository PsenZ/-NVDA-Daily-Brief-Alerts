from veyraquant.risk import budget_after, budget_exceeded, portfolio_heat_cap, position_size_pct


def test_position_size_respects_max_position_and_risk():
    sizing = position_size_pct(
        entry=100,
        stop=95,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        account_equity=100_000,
    )

    assert sizing.position_pct == 10
    assert sizing.max_loss_pct == 0.5
    assert sizing.position_value == 10_000


def test_portfolio_heat_cap_scales_position():
    position_pct, max_loss_pct = portfolio_heat_cap(10, 0.5, 0.25)

    assert position_pct == 5
    assert max_loss_pct == 0.25


def test_budget_guard_detects_limit_breaches():
    assert not budget_exceeded(0.5, 0.4, 1.0)
    assert budget_exceeded(0.7, 0.4, 1.0)
    assert not budget_exceeded(10.0, 5.0, None)
    assert budget_after(0.33333, 0.22222) == 0.5555
