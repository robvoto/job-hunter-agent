import json
from pathlib import Path
from typing import Dict, Optional

_BASE_DIR = Path(__file__).resolve().parent
_LOCATIONS_AU_PATH = _BASE_DIR / "data" / "locations_au.json"

_cached_locations: Optional[Dict[str, dict]] = None


def load_locations_au(force_reload: bool = False) -> dict:
    """
    Load canonical AU locations (states + capital cities only).
    Application-owned source of truth.
    """
    global _cached_locations

    if _cached_locations is not None and not force_reload:
        return _cached_locations

    if not _LOCATIONS_AU_PATH.exists():
        raise RuntimeError("locations_au.json is missing")

    _cached_locations = json.loads(_LOCATIONS_AU_PATH.read_text())
    return _cached_locations

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