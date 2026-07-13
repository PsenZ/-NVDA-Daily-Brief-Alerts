from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResearchNote:
    """LLM commentary. Deliberately a dead end: nothing in the decision
    pipeline consumes this type, so it cannot alter trading behavior."""
    symbol: str
    thesis: str
    counter_thesis: str
    uncertainty: str
    model: str = ""
    generated_at: str = ""
    evidence_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "thesis": self.thesis,
            "counter_thesis": self.counter_thesis,
            "uncertainty": self.uncertainty,
            "model": self.model,
            "generated_at": self.generated_at,
            "evidence_hash": self.evidence_hash,
        }
