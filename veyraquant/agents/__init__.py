"""Optional LLM research layer (R6).

Hard rules, enforced by structure and tests:
- reads ONLY structured Evidence (no prices, no plans, no raw text soup)
- outputs ONLY thesis / counter-thesis / uncertainty as ResearchNote
- a ResearchNote is never read by any decision path: it cannot change
  action, score, stop or position by construction
- disabled by default; any failure degrades to "no note", never breaks
  the pipeline; results are cached by (date, symbol, evidence_hash)
"""
