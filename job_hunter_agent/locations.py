"""Australian location resolution and proximity helpers.

This module manages the loading of canonical Australian states and capital
cities used by search pickers. It provides utilities for resolving
user-supplied location strings and calculating proximity to capital
cities using Haversine distance formulas.
"""

import json
import logging
from typing import Dict, Optional

from job_hunter_agent.paths import KNOWLEDGE_DIR

logger = logging.getLogger(__name__)

_LOCATIONS_AU_PATH = KNOWLEDGE_DIR / "locations_au.json"
LOCATION_GROUP_LABELS = {
    "state": "States",
    "city": "Capital cities",
    "territory": "Territories",
}

_cached_locations: Optional[Dict[str, dict]] = None
_cached_location_options: Optional[list[dict[str, str]]] = None


def _normalize_location_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def load_locations_au(force_reload: bool = False) -> dict:
    """
    Load canonical AU locations used by the search picker.
    Application-owned source of truth.
    """
    global _cached_locations

    if _cached_locations is not None and not force_reload:
        return _cached_locations

    if not _LOCATIONS_AU_PATH.exists():
        raise RuntimeError("locations_au.json is missing")

    _cached_locations = json.loads(_LOCATIONS_AU_PATH.read_text())
    return _cached_locations


def load_location_options(force_reload: bool = False) -> list[dict[str, str]]:
    """Return canonical AU location choices for the UI."""
    global _cached_location_options

    if _cached_location_options is not None and not force_reload:
        return _cached_location_options

    locations = load_locations_au(force_reload=force_reload)
    options: list[dict[str, str]] = []
    for entry in locations.values():
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in LOCATION_GROUP_LABELS:
            continue
        code = str(entry.get("code") or "").strip()
        label = str(entry.get("name") or "").strip()
        if not label:
            continue
        options.append(
            {
                "value": code or label,
                "label": label,
                "kind": kind,
                "group": LOCATION_GROUP_LABELS[kind],
            }
        )

    _cached_location_options = options
    return options


def default_location_value() -> str:
    """Pick a sensible default location from the canonical AU list."""
    options = load_location_options()
    for option in options:
        if option.get("kind") == "city":
            return str(option.get("value") or "").strip()
    return str(options[0].get("value") or "").strip() if options else ""


def resolve_location(raw: str) -> dict:
    """
    Resolve user-supplied location into a canonical location record.
    Rejects unsupported / regional / unknown locations.
    """
    locations = load_locations_au()

    key = _normalize_location_key(raw)

    for loc in locations.values():
        code = _normalize_location_key(loc.get("code", ""))
        name = _normalize_location_key(loc.get("name", ""))
        if key and key in {code, name}:
            return loc

    raise ValueError(f"Unsupported location: {raw}")


def find_nearest_location(latitude: float, longitude: float) -> str:
    """
    Find the nearest Australian city given latitude and longitude.

    Uses haversine distance calculation to find the closest capital city.
    Returns the city name or falls back to Sydney if calculation fails.

    Args:
        latitude: User's latitude
        longitude: User's longitude

    Returns:
        Nearest city name (e.g., "Sydney", "Melbourne"), or "Sydney" as fallback
    """
    import math

    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two coordinates in kilometers."""
        R = 6371  # Earth's radius in km
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    try:
        locations = load_locations_au()
        # Filter to only cities for more precise location detection
        cities = [
            (entry.get("name", ""), entry.get("lat"), entry.get("lon"))
            for entry in locations.values()
            if entry.get("kind") == "city"
            and entry.get("lat") is not None
            and entry.get("lon") is not None
        ]

        if not cities:
            return default_location_value()

        # Find nearest city
        nearest_city = min(
            cities, key=lambda city: haversine_distance(latitude, longitude, city[1], city[2])
        )
        return str(nearest_city[0]).strip()
    except Exception as exc:
        logger.warning(
            "[locations] find_nearest_location failed: %s. Falling back to default.", exc
        )
        # Fall back to Sydney if any error occurs
        return default_location_value()
