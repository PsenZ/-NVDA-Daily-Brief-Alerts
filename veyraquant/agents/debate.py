"""Deterministic bull/bear framing of the evidence trail.

Pure function - the LLM receives an already-structured debate, so its
job is compression and articulation, never discovery of new 'facts'."""
from typing import Any


def frame_debate(evidence: list[Any]) -> dict[str, list[str]]:
    bull: list[str] = []
    bear: list[str] = []
    context: list[str] = []
    for item in evidence:
        line = _line(item)
        polarity = getattr(item, "polarity", None) or (
            item.get("polarity") if isinstance(item, dict) else None
        )
        if polarity == "reason":
            bull.append(line)
        elif polarity == "risk":
            bear.append(line)
        else:
            context.append(line)
    return {"bull": bull, "bear": bear, "context": context}


def _line(item: Any) -> str:
    def get(field: str) -> Any:
        if isinstance(item, dict):
            return item.get(field)
        return getattr(item, field, None)

    code = get("code") or "?"
    text = get("text") or ""
    value = get("value")
    points = get("points")
    parts = [f"[{code}]", text]
    if value is not None:
        parts.append(f"(value={value})")
    if points is not None:
        parts.append(f"(points={points:+g})")
    return " ".join(str(part) for part in parts if part)
