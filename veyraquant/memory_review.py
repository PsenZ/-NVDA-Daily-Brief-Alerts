import json
from dataclasses import dataclass
from typing import Any


DIMENSIONS = ("setup_type", "action", "rating", "market_regime", "portfolio_decision")


@dataclass(frozen=True)
class ReviewSummary:
    dimension: str
    key: str
    count: int
    resolved_count: int
    unresolved_count: int
    avg_5d_return: float | None
    avg_alpha_vs_spy: float | None
    win_rate: float | None


def build_review_summaries(path: str, dimensions: tuple[str, ...] = DIMENSIONS) -> list[ReviewSummary]:
    entries = _read_entries(path)
    summaries: list[ReviewSummary] = []
    for dimension in dimensions:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            key = str(entry.get(dimension) or "unknown")
            buckets.setdefault(key, []).append(entry)
        for key, rows in buckets.items():
            summaries.append(_summarize_bucket(dimension, key, rows))
    return summaries


def brief_review_notes(path: str, limit: int = 2) -> list[str]:
    summaries = build_review_summaries(path, ("setup_type", "portfolio_decision"))
    candidates = [
        item
        for item in summaries
        if item.resolved_count >= 2 and item.avg_alpha_vs_spy is not None
    ]
    candidates.sort(key=lambda item: item.avg_alpha_vs_spy or 0.0, reverse=True)
    notes: list[str] = []
    for item in candidates[:limit]:
        notes.append(
            f"{item.dimension}:{item.key} avg 5D alpha {item.avg_alpha_vs_spy:+.2%} "
            f"over {item.resolved_count} resolved decision(s)."
        )
    return notes


def main() -> int:
    for summary in build_review_summaries("memory/decision_log.jsonl"):
        avg_alpha = "NA" if summary.avg_alpha_vs_spy is None else f"{summary.avg_alpha_vs_spy:+.4f}"
        win_rate = "NA" if summary.win_rate is None else f"{summary.win_rate:.2f}%"
        print(
            f"{summary.dimension}={summary.key} count={summary.count} "
            f"resolved={summary.resolved_count} unresolved={summary.unresolved_count} "
            f"avg_alpha_vs_spy={avg_alpha} win_rate={win_rate}"
        )
    return 0


def _summarize_bucket(dimension: str, key: str, rows: list[dict[str, Any]]) -> ReviewSummary:
    resolved = [row for row in rows if row.get("outcome_status") == "resolved"]
    unresolved_count = len([row for row in rows if row.get("outcome_status") != "resolved"])
    returns = [_as_float(row.get("five_day_return")) for row in resolved]
    alphas = [_as_float(row.get("alpha_vs_spy")) for row in resolved]
    returns = [value for value in returns if value is not None]
    alphas = [value for value in alphas if value is not None]
    win_rate = None
    if returns:
        wins = [value for value in returns if value > 0]
        win_rate = round(len(wins) / len(returns) * 100, 2)
    return ReviewSummary(
        dimension=dimension,
        key=key,
        count=len(rows),
        resolved_count=len(resolved),
        unresolved_count=unresolved_count,
        avg_5d_return=_avg(returns),
        avg_alpha_vs_spy=_avg(alphas),
        win_rate=win_rate,
    )


def _read_entries(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _as_float(value) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


if __name__ == "__main__":
    raise SystemExit(main())
