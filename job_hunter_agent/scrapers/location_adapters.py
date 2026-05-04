def to_jobspy(location: dict) -> str:
    """
    Convert canonical location → jobspy-compatible string.
    """
    return f"{location['capital']}, Australia"
