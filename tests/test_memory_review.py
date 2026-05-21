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
