"""
Pure functions for zone name matching and graph traversal.

No database or external dependencies - can be used in tests and CLI tools.
"""

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# Starting node (always discovered)
START_NODE = "Chapel of Anticipation"


def strip_parenthetical(name: str) -> str:
    """Strip parenthetical suffix from zone name.

    Spoiler log names can have detail text like:
    "Zone Name (detail text)" -> "Zone Name"
    """
    return re.sub(r"\s*\([^)]+\)$", "", name)


def names_match(a: str, b: str) -> bool:
    """Check if two zone names match (exact or normalized without parentheses)."""
    return a == b or strip_parenthetical(a) == b or a == strip_parenthetical(b)


def is_one_way(link: dict, all_links: list[dict]) -> bool:
    """A link is one-way if no reverse link exists."""
    return not any(
        other["source"] == link["destination"] and other["destination"] == link["source"]
        for other in all_links
    )


def build_preexisting_adjacency(
    zone_pairs: list[dict],
) -> dict[str, list[tuple[str, bool]]]:
    """
    Build adjacency list for preexisting links only.
    Returns dict[source] -> list of (destination, is_bidirectional)
    """
    adj: dict[str, list[tuple[str, bool]]] = defaultdict(list)

    for pair in zone_pairs:
        if pair["type"] == "preexisting":
            is_bidir = not is_one_way(pair, zone_pairs)
            adj[pair["source"]].append((pair["destination"], is_bidir))
            if is_bidir:
                adj[pair["destination"]].append((pair["source"], True))

    return adj


def get_discovered_nodes(discovered_links: list[dict]) -> set[str]:
    """
    Get all discovered nodes from discovered links.
    A node is discovered if it's the source or target of any discovered link,
    or is START_NODE.
    """
    discovered = {START_NODE}

    for link in discovered_links:
        discovered.add(link["source"])
        discovered.add(link["target"])

    return discovered


def link_exists(discovered_links: list[dict], source: str, target: str) -> bool:
    """Check if a link already exists in discovered_links."""
    return any(dl["source"] == source and dl["target"] == target for dl in discovered_links)


def find_zone_pair(zone_pairs: list[dict], source: str, target: str) -> dict | None:
    """Find a zone pair matching source and target (in either direction for random links).

    Compares both exact names and normalized names (without parenthetical text).
    """
    for pair in zone_pairs:
        pair_source = pair["source"]
        pair_target = pair["destination"]

        # Check direct match (exact or normalized)
        source_matches = names_match(pair_source, source)
        target_matches = names_match(pair_target, target)
        if source_matches and target_matches:
            return pair

        # For random links, also check reverse (they're bidirectional)
        if pair["type"] == "random":
            source_matches_rev = names_match(pair_source, target)
            target_matches_rev = names_match(pair_target, source)
            if source_matches_rev and target_matches_rev:
                return pair

    return None


def find_matching_zone_pair(
    zone_pairs: list[dict],
    source_candidates: list[tuple[str, str]],
    target_candidates: list[tuple[str, str]],
) -> tuple[str, str, dict] | None:
    """
    Find a matching zone pair from lists of candidates.

    Tries all combinations of source and target candidates until finding
    a match in zone_pairs. Candidates are assumed to be ordered by likelihood.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        source_candidates: List of (internal_name, display_name) for source, best first
        target_candidates: List of (internal_name, display_name) for target, best first

    Returns:
        Tuple of (source_display, target_display, zone_pair) if found, None otherwise.
    """
    for source_internal, source_display in source_candidates:
        for target_internal, target_display in target_candidates:
            pair = find_zone_pair(zone_pairs, source_display, target_display)
            if pair:
                logger.debug(
                    "[MATCH] Found pair: '%s' → '%s' (tried %s → %s)",
                    source_display,
                    target_display,
                    source_internal,
                    target_internal,
                )
                return source_display, target_display, pair

    return None


def find_all_matching_zone_pairs(
    zone_pairs: list[dict],
    source_candidates: list[tuple[str, str]],
    target_candidates: list[tuple[str, str]],
) -> list[tuple[str, str, dict]]:
    """
    Find ALL matching zone pairs from lists of candidates.

    Unlike find_matching_zone_pair which returns the first match, this returns
    all valid combinations. Used when we want to discover all possible links
    to avoid missing the correct one in ambiguous cases.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        source_candidates: List of (internal_name, display_name) for source
        target_candidates: List of (internal_name, display_name) for target

    Returns:
        List of (source_display, target_display, zone_pair) tuples for all matches.
        Deduplicated by link (A↔B counted once regardless of direction).
    """
    matches = []
    seen_links = set()  # Track unique links to avoid duplicates

    for _source_internal, source_display in source_candidates:
        for _target_internal, target_display in target_candidates:
            pair = find_zone_pair(zone_pairs, source_display, target_display)
            if pair and pair["type"] == "random":
                # Use frozenset to deduplicate bidirectional links
                link_key = frozenset([pair["source"], pair["destination"]])
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    # Return the actual names from the spoiler log pair
                    matches.append((pair["source"], pair["destination"], pair))
                    logger.debug(
                        "[MATCH] Found pair: '%s' → '%s'",
                        pair["source"],
                        pair["destination"],
                    )

    return matches


def find_candidate_zones(zone_pairs: list[dict], zone_name: str) -> list[dict]:
    """Find all zone pairs that contain a zone name (for debugging)."""
    candidates = []
    for pair in zone_pairs:
        if pair["source"] == zone_name or pair["destination"] == zone_name:
            candidates.append(pair)
    return candidates


def find_similar_zones(zone_pairs: list[dict], zone_name: str, limit: int = 5) -> list[str]:
    """Find zones with similar names (for debugging mismatches)."""
    all_zones = set()
    for pair in zone_pairs:
        all_zones.add(pair["source"])
        all_zones.add(pair["destination"])

    # Simple substring matching
    zone_lower = zone_name.lower()
    similar = []
    for zone in all_zones:
        if (
            zone_lower in zone.lower()
            or zone.lower() in zone_lower
            or set(zone_lower.split()) & set(zone.lower().split())
        ):
            similar.append(zone)

    return similar[:limit]


def compute_total_zones(zone_pairs: list[dict]) -> int:
    """Compute total unique zones from zone pairs."""
    zones = set()
    for pair in zone_pairs:
        zones.add(pair["source"])
        zones.add(pair["destination"])
    return len(zones)
