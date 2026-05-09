def to_jobspy(location: dict) -> str:
    """
    Convert canonical location → jobspy-compatible string.

    City-level inputs (resolved by city alias) return "{city}, Australia".
    State/territory inputs return "{state name}, Australia".
    """
    kind = str(location.get("kind") or "").strip().lower()
    if kind in {"state", "territory"}:
        return f"{location['name']}, Australia"
    return f"{location['capital']}, Australia"
