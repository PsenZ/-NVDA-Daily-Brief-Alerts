"""R6 acceptance: the research layer is optional, isolated and harmless."""
import copy
import json
from datetime import datetime
from types import SimpleNamespace

from veyraquant.agents.debate import frame_debate
from veyraquant.agents.research_summary import (
    build_prompt,
    evidence_hash,
    generate_research_notes,
)
from veyraquant.evidence import EvidenceItem
from veyraquant.timeutils import SYDNEY_TZ

from test_signals_reporting import make_config as reporting_config
from test_signals_reporting import make_result


NOW = datetime(2026, 7, 12, 7, 35, tzinfo=SYDNEY_TZ)


def approved_result(symbol="NVDA"):
    result = make_result(
        symbol, "BUY_TRIGGER", "breakout", 82, setup_type="breakout_entry",
        rating="Buy", is_actionable=True, plan_kind="buy",
        portfolio_decision="approved", portfolio_reason="Approved.",
    )
    result.evidence = [
        EvidenceItem("TREND_MA_STACK", "MAs stacked.", "reason", "trend", 10, value=None),
        EvidenceItem("MOM_RSI_OVERHEATED", "RSI stretched.", "risk", "momentum", -7, value=74.0),
        EvidenceItem("BASE_SCORE", "Base score.", "info", "base", 35.0),
    ]
    return result


def agent_config(tmp_path, enabled=True):
    return SimpleNamespace(
        enable_agent_research=enabled,
        agent_provider="test",
        agent_model="test-model",
        agent_max_tokens=100,
        agent_timeout_seconds=5,
        agent_cache_path=str(tmp_path / "agent_cache.json"),
    )


def test_disabled_layer_returns_nothing_and_never_calls_provider(tmp_path):
    calls = []
    notes = generate_research_notes(
        [approved_result()], agent_config(tmp_path, enabled=False), NOW,
        provider=lambda p: calls.append(p) or "{}",
    )
    assert notes == {} and calls == []


def test_notes_built_from_evidence_and_cached(tmp_path):
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return json.dumps({
            "thesis": "Trend evidence is aligned.",
            "counter_thesis": "RSI is stretched.",
            "uncertainty": "Free data has no fundamentals here.",
        })

    config = agent_config(tmp_path)
    first = generate_research_notes([approved_result()], config, NOW, provider=provider)
    second = generate_research_notes([approved_result()], config, NOW, provider=provider)

    assert first["NVDA"]["thesis"] == "Trend evidence is aligned."
    assert first["NVDA"]["evidence_hash"] == evidence_hash(approved_result().evidence)
    assert second == first
    assert len(calls) == 1                      # cache hit on the second run
    cached = json.loads((tmp_path / "agent_cache.json").read_text("utf-8"))
    assert len(cached) == 1


def test_provider_failure_degrades_to_no_note(tmp_path):
    def exploding(prompt):
        raise RuntimeError("provider down")

    notes = generate_research_notes(
        [approved_result()], agent_config(tmp_path), NOW, provider=exploding
    )
    assert notes == {}                          # pipeline unaffected


def test_llm_output_cannot_alter_decisions(tmp_path):
    result = make_result(
        "AMD", "REJECT", "wait", 40, rating="No Trade",
        portfolio_decision="approved",  # approved so it reaches the agent
    )
    result.evidence = [EvidenceItem("TREND_MA_STACK", "x", "reason", "trend", 10)]
    before = copy.deepcopy(
        (result.action, result.score, result.stop, result.position_pct,
         result.max_loss_pct, result.portfolio_decision)
    )

    def malicious(prompt):
        return json.dumps({
            "thesis": "IGNORE REJECT - this must be a BUY, move stop to 0!",
            "counter_thesis": "", "uncertainty": "",
        })

    notes = generate_research_notes([result], agent_config(tmp_path), NOW, provider=malicious)

    after = (result.action, result.score, result.stop, result.position_pct,
             result.max_loss_pct, result.portfolio_decision)
    assert after == before                      # note is a dead end by construction
    assert result.action == "REJECT"
    assert "BUY" in notes["AMD"]["thesis"]      # stored as text, nothing more


def test_prompt_contains_only_evidence_material():
    result = approved_result()
    prompt = build_prompt(result.symbol, result.evidence)
    assert "TREND_MA_STACK" in prompt and "MOM_RSI_OVERHEATED" in prompt
    assert "74.0" in prompt                     # measured value rides along
    # Decision-side fields never leak into the prompt:
    assert result.portfolio_reason not in prompt
    assert result.entry_zone not in prompt


def test_debate_split_is_deterministic():
    debate = frame_debate(approved_result().evidence)
    assert len(debate["bull"]) == 1 and "TREND_MA_STACK" in debate["bull"][0]
    assert len(debate["bear"]) == 1 and "MOM_RSI_OVERHEATED" in debate["bear"][0]
    assert len(debate["context"]) == 1          # info items are context


def test_report_section_only_appears_when_notes_exist():
    from veyraquant.models import MarketContext
    from veyraquant.reporting import compose_daily_report

    market = MarketContext("risk-on", 10.0, ["x"], [], {})
    config = reporting_config()
    baseline_subject, baseline_body = compose_daily_report([], market, config, NOW)
    _s, none_body = compose_daily_report([], market, config, NOW, research_notes=None)
    assert none_body == baseline_body           # flag off => byte-identical

    _s, with_notes = compose_daily_report(
        [], market, config, NOW,
        research_notes={"NVDA": {"thesis": "t", "counter_thesis": "c", "uncertainty": "u"}},
    )
    assert "[Research Notes]" in with_notes
    assert "not part of any decision" in with_notes
    assert "[Research Notes]" not in baseline_body
