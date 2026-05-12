import json
from typing import Dict, Optional

from job_hunter_agent.paths import DATA_DIR

_LOCATIONS_AU_PATH = DATA_DIR / "locations_au.json"
LOCATION_GROUP_LABELS = {
    "state": "States",
    "city": "Capital cities",
    "territory": "Territories",
}

_cached_locations: Optional[Dict[str, dict]] = None
_cached_location_options: Optional[list[dict[str, str]]] = None


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
        label = str(entry.get("name") or "").strip()
        if not label:
            continue
        options.append(
            {
                "value": label,
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

    key = raw.strip().lower()

    for loc in locations.values():
        aliases = [a.lower() for a in loc.get("aliases", [])]
        if key == loc["code"].lower() or key in aliases:
            return loc

    raise ValueError(f"Unsupported location: {raw}")
