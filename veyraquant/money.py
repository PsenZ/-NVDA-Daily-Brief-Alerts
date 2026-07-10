def parse_money(value) -> float | None:
    """Parse a money-like value ("$1,234.50", 12.3, None) into a float.

    Returns None for None/""/"NA" or anything that cannot be parsed.
    """
    if value in {None, "", "NA"}:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None
