import numpy as np
import pandas as pd

from veyraquant.walkforward import FoldResult, _grid_combos, summarize, walk_forward

from test_backtest import make_config


def trending_frame(rows=260, start=100, step=0.3):
    close = start + np.arange(rows) * step
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.2,
            "Low": close - 1.2,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_500_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def flat_frame(rows=260):
    rng = np.random.default_rng(11)
    close = 100 + rng.normal(0, 0.05, rows).cumsum()
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.1,
            "Low": close - 0.1,
            "Close": close,
            "Volume": np.full(rows, 1_000_000.0),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def test_grid_combos_cartesian_product_and_empty_grid():
    combos = _grid_combos({"a": [1, 2], "b": [3]})
    assert combos == [{"a": 1, "b": 3}, {"a": 2, "b": 3}]
    assert _grid_combos({}) == [{}]


def test_fold_layout_and_identity_grid_matches_baseline():
    daily = trending_frame(260)
    folds = walk_forward(
        "NVDA",
        daily,
        make_config(),
        param_grid={},  # single empty combo == default thresholds
        train_bars=150,
        valid_bars=50,
        step_bars=50,
        min_train_trades=0,
    )

    assert len(folds) == 2
    assert (folds[0].train_start, folds[0].train_end, folds[0].valid_end) == (0, 150, 200)
    assert (folds[1].train_start, folds[1].train_end, folds[1].valid_end) == (50, 200, 250)
    for fold in folds:
        # Tuning with the default params must reproduce the baseline exactly:
        # proves the valid evaluation path is identical for both.
        assert fold.best_params == {}
        assert fold.valid_avg_r == fold.baseline_valid_avg_r
        assert fold.valid_trades == fold.baseline_valid_trades


def test_fold_without_qualifying_train_trades_reports_none():
    daily = flat_frame(260)
    folds = walk_forward(
        "NVDA",
        daily,
        make_config(),
        param_grid={},
        train_bars=150,
        valid_bars=50,
        min_train_trades=5,  # flat tape cannot produce 5 train trades
    )

    assert folds
    assert all(fold.best_params is None for fold in folds)
    assert all(fold.valid_avg_r is None for fold in folds)

    report = summarize(folds)
    assert report["tuned_valid_trades"] == 0
    assert "insufficient evidence" in report["verdict"]


def test_summarize_pools_by_trade_count_and_guards_thin_samples():
    def fold(fold_id, valid_r, valid_n, base_r, base_n):
        return FoldResult(
            fold=fold_id,
            train_start=0,
            train_end=150,
            valid_end=200,
            best_params={"x": 1},
            train_avg_r=0.5,
            train_trades=10,
            valid_avg_r=valid_r,
            valid_trades=valid_n,
            baseline_valid_avg_r=base_r,
            baseline_valid_trades=base_n,
        )

    # 20 trades at +0.5R and 20 at -0.1R -> pooled +0.2R over 40 trades.
    report = summarize([fold(0, 0.5, 20, 0.1, 20), fold(1, -0.1, 20, 0.0, 20)])
    assert report["tuned_pooled_avg_r"] == 0.2
    assert report["tuned_valid_trades"] == 40
    assert "positive out-of-sample" in report["verdict"]

    # Same numbers but only 8 trades total -> verdict must refuse to conclude.
    thin = summarize([fold(0, 0.5, 4, 0.1, 4), fold(1, -0.1, 4, 0.0, 4)])
    assert "insufficient evidence" in thin["verdict"]


def test_trade_sink_collects_attributed_validation_trades(monkeypatch):
    from types import SimpleNamespace
    from veyraquant.models import DataQuality, TradePlan

    def fake_analyze(symbol, daily, intraday, fundamentals, options, news, market, config, **kwargs):
        actionable = len(daily) - 1 >= 100
        plan = TradePlan(
            entry_zone="z", stop="s", targets="t", position_pct=6.0, max_loss_pct=0.5,
            rr=1.8, trigger="x", cancel="y",
            entry_low=100.0, entry_high=101.0, stop_price=96.0, target1=107.0, target2=112.0,
        )
        return SimpleNamespace(
            is_actionable=actionable, trade_plan=plan, score=77,
            setup_type="breakout_entry", market_regime="risk-on",
            sector_bucket="semiconductor",
            data_quality=DataQuality(data_quality_level="HIGH"),
        )

    monkeypatch.setattr("veyraquant.signals.analyze_symbol", fake_analyze)

    daily = trending_frame(160, 100, 0.0)  # flat: timeout exits, deterministic
    sink: list = []
    folds = walk_forward(
        "NVDA", daily, make_config(), param_grid={}, train_bars=130, valid_bars=30,
        min_train_trades=1, trade_sink=sink,
    )

    assert folds and folds[0].valid_trades == len(sink)
    assert sink, "validation trades should reach the sink"
    assert all(t.setup_type == "breakout_entry" for t in sink)
    assert all(t.market_regime == "risk-on" for t in sink)
    assert all(t.exit_reason for t in sink)  # taxonomy-ready
