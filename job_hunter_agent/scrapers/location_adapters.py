def to_seek(location: dict) -> str:
    """Convert canonical location to the SEEK query token."""
    return str(location.get("code") or "").strip()


def to_jobspy(location: dict) -> str:
    """Convert canonical location to the jobspy location string."""
    kind = str(location.get("kind") or "").strip().lower()
    if kind in {"state", "territory"}:
        return f"{location['name']}, Australia"
    return f"{location['capital']}, Australia"
