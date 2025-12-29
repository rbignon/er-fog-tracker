"""
Grace entity ID to zone mapping resolver.

This module provides fast lookup of zone names from grace entity IDs,
enabling precise zone resolution for fast travel destinations.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Global singleton for the grace mapping
_grace_mapping: dict[str, dict] | None = None


def _load_grace_mapping() -> dict[str, dict]:
    """Load grace mapping from JSON file."""
    data_dir = Path(__file__).parent.parent / "data"
    graces_file = data_dir / "graces.json"

    if not graces_file.exists():
        logger.warning("Grace mapping file not found: %s", graces_file)
        return {}

    try:
        with open(graces_file) as f:
            data = json.load(f)
            mapping = data.get("mapping", {})
            logger.info(
                "Loaded grace mapping: %d entries",
                len(mapping),
            )
            return mapping
    except Exception as e:
        logger.error("Failed to load grace mapping: %s", e)
        return {}


def get_grace_mapping() -> dict[str, dict]:
    """Get the grace entity ID to zone mapping (lazy-loaded singleton)."""
    global _grace_mapping
    if _grace_mapping is None:
        _grace_mapping = _load_grace_mapping()
    return _grace_mapping


def resolve_zone_by_grace_entity_id(grace_entity_id: int | str) -> str | None:
    """Resolve zone display name from grace entity ID.

    Args:
        grace_entity_id: The entity ID of the grace (e.g., 1042362951 for "The First Step")

    Returns:
        Zone display name if found, None otherwise.
    """
    mapping = get_grace_mapping()
    entity_id_str = str(grace_entity_id)

    entry = mapping.get(entity_id_str)
    if entry:
        zone = entry.get("zone")
        grace_name = entry.get("grace_name")
        logger.debug(
            "Grace entity %s resolved to zone '%s' (grace: %s)",
            entity_id_str,
            zone,
            grace_name,
        )
        return zone

    logger.debug("Grace entity %s not found in mapping", entity_id_str)
    return None


def get_grace_info(grace_entity_id: int | str) -> dict | None:
    """Get full grace info from entity ID.

    Args:
        grace_entity_id: The entity ID of the grace

    Returns:
        Dict with grace_name, zone, map_id if found, None otherwise.
    """
    mapping = get_grace_mapping()
    return mapping.get(str(grace_entity_id))
