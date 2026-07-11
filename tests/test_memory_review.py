import json

from veyraquant.memory_review import brief_review_notes, build_review_summaries


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_memory_review_aggregates_resolved_and_unresolved_rows(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    write_jsonl(
        path,
        [
            {
                "setup_type": "breakout_entry",
                "action": "BUY_TRIGGER",
                "rating": "Buy",
                "market_regime": "risk-on",
                "portfolio_decision": "approved",
                "outcome_status": "resolved",
                "five_day_return": 0.04,
                "alpha_vs_spy": 0.03,
            },
            {
                "setup_type": "breakout_entry",
                "action": "BUY_TRIGGER",
                "rating": "Buy",
                "market_regime": "risk-on",
                "portfolio_decision": "approved",
                "outcome_status": "resolved",
                "five_day_return": -0.02,
                "alpha_vs_spy": -0.01,
            },
            {
                "setup_type": "breakout_entry",
                "action": "BUY_TRIGGER",
                "rating": "Buy",
                "market_regime": "risk-on",
                "portfolio_decision": "approved",
                "outcome_status": "pending",
            },
        ],
    )

    summaries = build_review_summaries(str(path), ("setup_type",))
    summary = summaries[0]

    assert summary.key == "breakout_entry"
    assert summary.count == 3
    assert summary.resolved_count == 2
    assert summary.unresolved_count == 1
    assert summary.avg_5d_return == 0.01
    assert summary.avg_alpha_vs_spy == 0.01
    assert summary.win_rate == 50.0


def test_brief_review_notes_only_use_resolved_samples(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    write_jsonl(
        path,
        [
            {
                "setup_type": "pullback_add",
                "portfolio_decision": "approved",
                "outcome_status": "resolved",
                "five_day_return": 0.03,
                "alpha_vs_spy": 0.02,
            },
            {
                "setup_type": "pullback_add",
                "portfolio_decision": "approved",
                "outcome_status": "resolved",
                "five_day_return": 0.05,
                "alpha_vs_spy": 0.04,
            },
            {
                "setup_type": "breakout_entry",
                "portfolio_decision": "approved",
                "outcome_status": "pending",
            },
        ],
    )

    notes = brief_review_notes(str(path))

    assert notes
    assert notes[0].startswith("setup_type:pullback_add")
    assert "avg 5D alpha +3.00%" in notes[0]


def test_t_stat_ci_and_significance_with_large_sample(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    # 12 resolved rows, alphas alternating +2%/+4% -> mean +3%, clearly > 0.
    rows = [
        {
            "setup_type": "breakout_entry",
            "outcome_status": "resolved",
            "five_day_return": 0.05,
            "alpha_vs_spy": 0.02 if i % 2 == 0 else 0.04,
        }
        for i in range(12)
    ]
    write_jsonl(path, rows)

    summary = build_review_summaries(str(path), ("setup_type",))[0]

    assert summary.avg_alpha_vs_spy == 0.03
    assert summary.t_stat is not None and summary.t_stat > 2.0
    assert summary.ci_low is not None and summary.ci_low > 0
    assert summary.ci_high is not None and summary.ci_high > summary.ci_low
    assert summary.significant is True


def test_small_samples_are_never_flagged_significant(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    rows = [
        {"setup_type": "x", "outcome_status": "resolved", "five_day_return": 0.05, "alpha_vs_spy": 0.03},
        {"setup_type": "x", "outcome_status": "resolved", "five_day_return": 0.04, "alpha_vs_spy": 0.02},
        {"setup_type": "x", "outcome_status": "resolved", "five_day_return": 0.06, "alpha_vs_spy": 0.04},
    ]
    write_jsonl(path, rows)

    summary = build_review_summaries(str(path), ("setup_type",))[0]

    # t exists (n=3) but n < 10 must block the significance flag.
    assert summary.t_stat is not None
    assert summary.significant is False

    notes = brief_review_notes(str(path))
    assert notes and "not significant" in notes[0]


def test_score_band_dimension_buckets_scores(tmp_path):
    path = tmp_path / "decision_log.jsonl"
    rows = [
        {"score": 82, "outcome_status": "resolved", "five_day_return": 0.05, "alpha_vs_spy": 0.03},
        {"score": 70, "outcome_status": "resolved", "five_day_return": 0.01, "alpha_vs_spy": 0.0},
        {"score": 40, "outcome_status": "pending"},
    ]
    write_jsonl(path, rows)

    summaries = build_review_summaries(str(path), ("score_band",))
    keys = {summary.key for summary in summaries}

    assert keys == {"75+", "65-74", "<55"}


def test_horizon_summaries_compare_holding_periods(tmp_path):
    from veyraquant.memory_review import build_horizon_summaries

    path = tmp_path / "decision_log.jsonl"
    rows = [
        {
            "outcome_status": "resolved",
            "horizon_alphas": {"1": 0.001 * i, "3": 0.002 * i, "5": 0.004 * i, "10": -0.001 * i},
        }
        for i in range(1, 5)
    ]
    # One row missing the 10d horizon: it must be skipped there, not zeroed.
    rows.append({"outcome_status": "resolved", "horizon_alphas": {"1": 0.01, "3": 0.01, "5": 0.01}})
    write_jsonl(path, rows)

    summaries = {item.horizon: item for item in build_horizon_summaries(str(path))}

    assert summaries[5].count == 5
    assert summaries[10].count == 4
    assert summaries[10].avg_alpha < 0 < summaries[5].avg_alpha
    assert summaries[1].win_rate == 100.0
