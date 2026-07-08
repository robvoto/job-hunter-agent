"""Scraper helpers for source-specific location adapters."""

from __future__ import annotations

LINKEDIN_CITY_RADIUS_MILES = 50


def _clean_location_field(location: dict, key: str) -> str:
    value = str(location.get(key) or "").strip()
    if not value:
        raise ValueError(f"Unsupported location record: missing {key}")
    return value


def to_seek(location: dict) -> str:
    """Convert a canonical location to the SEEK query token."""

    return _clean_location_field(location, "code")


def to_linkedin_search_scope(location: dict) -> dict[str, int | str | None]:
    """Convert a canonical location to an explicit LinkedIn search scope.

    City searches use a radius around the city. State and territory searches
    use the broader state/territory name without a radius.
    """

    kind = str(location.get("kind") or "").strip().lower()
    if kind == "city":
        city = _clean_location_field(location, "capital")
        return {
            "location": f"{city}, Australia",
            "distance": LINKEDIN_CITY_RADIUS_MILES,
            "scope": "city_radius",
        }
    if kind in {"state", "territory"}:
        state = _clean_location_field(location, "name")
        return {
            "location": f"{state}, Australia",
            "distance": None,
            "scope": "state",
        }
    raise ValueError(f"Unsupported location kind for LinkedIn: {kind or 'unknown'}")
