"""Research-note generation: Evidence in, ResearchNote out, nothing else.

The provider is pluggable (tests inject a callable); the built-in
"openai" provider posts to the chat-completions API with a strict-JSON
instruction. Every failure path degrades to "no note for this symbol"
with a warning - the email pipeline can never be harmed from here.
"""
import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Callable, Optional

from .debate import frame_debate
from .schemas import ResearchNote


logger = logging.getLogger(__name__)

MAX_NOTES_PER_RUN = 3  # approved names only; keeps cost and latency bounded

PROMPT_TEMPLATE = """You are a sell-side research summarizer. You receive ONLY a
structured evidence trail for {symbol} produced by a deterministic
rules engine. Do not invent facts beyond this evidence. Do not give
price targets, position sizes, or instructions - the trading decision
is already made elsewhere and you cannot change it.

BULL EVIDENCE:
{bull}

BEAR EVIDENCE:
{bear}

CONTEXT:
{context}

Respond with STRICT JSON, no markdown, exactly these keys:
{{"thesis": "<=60 words for the bull case grounded in the evidence",
"counter_thesis": "<=60 words for the bear case grounded in the evidence",
"uncertainty": "<=40 words on what the evidence cannot tell us"}}"""


def evidence_hash(evidence: list[Any]) -> str:
    ids = sorted(
        str(getattr(item, "evidence_id", None) or (item.get("evidence_id") if isinstance(item, dict) else ""))
        for item in evidence
    )
    return hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:16]


def build_prompt(symbol: str, evidence: list[Any]) -> str:
    debate = frame_debate(evidence)
    return PROMPT_TEMPLATE.format(
        symbol=symbol,
        bull="\n".join(debate["bull"]) or "(none)",
        bear="\n".join(debate["bear"]) or "(none)",
        context="\n".join(debate["context"]) or "(none)",
    )


def parse_response(symbol: str, text: str) -> tuple[str, str, str]:
    try:
        payload = json.loads(text)
        return (
            str(payload.get("thesis", "")).strip(),
            str(payload.get("counter_thesis", "")).strip(),
            str(payload.get("uncertainty", "")).strip(),
        )
    except Exception:
        logger.warning("%s research response was not strict JSON; storing raw.", symbol)
        return text.strip()[:400], "", "unparsed model output"


def generate_research_notes(
    results: list[Any],
    config: Any,
    now_dt: datetime,
    provider: Optional[Callable[[str], str]] = None,
) -> dict[str, dict[str, Any]]:
    """Returns {symbol: note_dict} for approved results, or {} when the
    layer is disabled or everything fails. NEVER mutates results."""
    if not getattr(config, "enable_agent_research", False):
        return {}

    candidates = [
        result for result in results
        if getattr(result, "portfolio_decision", "") == "approved"
        and getattr(result, "evidence", None)
    ][:MAX_NOTES_PER_RUN]
    if not candidates:
        return {}

    call = provider or _configured_provider(config)
    if call is None:
        logger.warning("Agent research enabled but no usable provider; skipping.")
        return {}

    cache_path = getattr(config, "agent_cache_path", "") or ""
    cache = _load_cache(cache_path)
    date = now_dt.strftime("%Y-%m-%d")
    notes: dict[str, dict[str, Any]] = {}

    for result in candidates:
        symbol = result.symbol
        ehash = evidence_hash(result.evidence)
        key = f"{date}|{symbol}|{ehash}"
        cached = cache.get(key)
        if cached:
            notes[symbol] = cached
            continue
        try:
            raw = call(build_prompt(symbol, result.evidence))
            thesis, counter, uncertainty = parse_response(symbol, raw)
            note = ResearchNote(
                symbol=symbol,
                thesis=thesis,
                counter_thesis=counter,
                uncertainty=uncertainty,
                model=str(getattr(config, "agent_model", "")),
                generated_at=now_dt.isoformat(),
                evidence_hash=ehash,
            ).to_dict()
            notes[symbol] = note
            cache[key] = note
        except Exception:
            logger.warning("Research note failed for %s; continuing.", symbol, exc_info=True)

    _save_cache(cache_path, cache)
    return notes


def _configured_provider(config: Any) -> Optional[Callable[[str], str]]:
    provider_name = str(getattr(config, "agent_provider", "") or "").lower()
    if provider_name != "openai":
        return None
    api_key = os.getenv("AGENT_API_KEY", "")
    if not api_key:
        return None

    def call(prompt: str) -> str:
        import requests

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": getattr(config, "agent_model", "gpt-4o-mini"),
                "max_tokens": int(getattr(config, "agent_max_tokens", 400)),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=float(getattr(config, "agent_timeout_seconds", 30)),
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    return call


def _load_cache(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("Unreadable agent cache; starting fresh.", exc_info=True)
        return {}


def _save_cache(path: str, cache: dict[str, Any]) -> None:
    if not path:
        return
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        logger.warning("Agent cache write failed.", exc_info=True)
