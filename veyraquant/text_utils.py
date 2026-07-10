def dedupe(items: list[str], drop_empty: bool = False) -> list[str]:
    """Return items with duplicates removed, preserving first-seen order.

    When drop_empty is True, falsy items (empty strings) are skipped.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if drop_empty and not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
