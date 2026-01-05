"""
Pure functions for zone name matching and graph traversal.

No database or external dependencies - can be used in tests and CLI tools.
"""

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)


def get_zone_link_id(link: dict) -> str | None:
    """Get the zone_link_id from a link dict, with legacy fallback.

    Handles both new format (zone_link_id) and legacy format (link_id).
    """
    return link.get("zone_link_id") or link.get("link_id")


def strip_parenthetical(name: str) -> str:
    """Strip parenthetical suffix from zone name.

    Spoiler log names can have detail text like:
    "Zone Name (detail text)" -> "Zone Name"
    """
    return re.sub(r"\s*\([^)]+\)$", "", name)


def names_match(a: str, b: str) -> bool:
    """Check if two zone names match (exact or normalized without parentheses)."""
    return a == b or strip_parenthetical(a) == b or a == strip_parenthetical(b)


def build_preexisting_adjacency(
    zone_pairs: list[dict],
) -> dict[str, list[tuple[str, bool]]]:
    """
    Build adjacency list for preexisting links only, keyed by zone_id.
    Returns dict[source_id] -> list of (target_id, is_bidirectional)

    A link is bidirectional unless marked as one-way (is_one_way: true).
    Most preexisting links (e.g., elevators, doors) are bidirectional.
    """
    adj: dict[str, list[tuple[str, bool]]] = defaultdict(list)

    for pair in zone_pairs:
        if pair["type"] == "preexisting":
            source_id = pair["source_id"]
            target_id = pair["target_id"]
            is_bidir = not pair.get("is_one_way", False)
            adj[source_id].append((target_id, is_bidir))
            if is_bidir:
                adj[target_id].append((source_id, True))

    return adj


def build_full_adjacency(
    zone_pairs: list[dict],
) -> dict[str, list[tuple[str, bool, dict]]]:
    """
    Build adjacency list for ALL links (random and preexisting), keyed by zone_id.
    Returns dict[source_id] -> list of (target_id, is_bidirectional, pair)

    All links are bidirectional unless marked as one-way (is_one_way: true).
    One-way links include sending gates, coffins, drop-downs, etc.
    """
    adj: dict[str, list[tuple[str, bool, dict]]] = defaultdict(list)

    for pair in zone_pairs:
        source_id = pair["source_id"]
        target_id = pair["target_id"]
        is_bidir = not pair.get("is_one_way", False)

        adj[source_id].append((target_id, is_bidir, pair))
        if is_bidir:
            adj[target_id].append((source_id, True, pair))

    return adj


def build_zone_pairs_index(zone_pairs: list[dict]) -> dict[str, dict]:
    """Build an index of zone_pairs by their ID for fast lookup."""
    return {zp["id"]: zp for zp in zone_pairs if zp.get("id")}


def expand_discovered_links(discovered_links: list[dict], zone_pairs: list[dict]) -> list[dict]:
    """
    Filter discovered_links to only include valid zone_link_ids.
    Returns list of {zone_link_id} - client resolves source/target from its linkIndex.
    """
    import logging

    logger = logging.getLogger(__name__)

    zp_index = build_zone_pairs_index(zone_pairs)
    valid_links = []
    skipped = []

    for link in discovered_links:
        link_id = get_zone_link_id(link)
        if link_id and link_id in zp_index:
            valid_links.append({"zone_link_id": link_id})
        else:
            skipped.append(link_id)

    if skipped:
        logger.warning(
            "[EXPAND] Skipped %d links (not in zone_pairs): %s",
            len(skipped),
            skipped[:10],  # Show first 10
        )

    return valid_links


def get_discovered_nodes(
    discovered_links: list[dict],
    zone_pairs: list[dict],
    starting_zone_id: str,
) -> set[str]:
    """
    Get all discovered zone_ids from discovered links.
    A node is discovered if it's the source or target of any discovered link,
    or is the starting_zone_id.
    """
    discovered = {starting_zone_id}
    zp_index = build_zone_pairs_index(zone_pairs)

    for link in discovered_links:
        link_id = get_zone_link_id(link)
        zp = zp_index.get(link_id)
        if zp:
            discovered.add(zp["source_id"])
            discovered.add(zp["target_id"])

    return discovered


def link_exists(
    discovered_links: list[dict],
    source_id: str,
    target_id: str,
    zone_pairs: list[dict],
) -> bool:
    """Check if a link already exists in discovered_links.

    For bidirectional random links, also checks the reverse direction since
    discovering A→B is equivalent to discovering B→A for the same fog gate.

    Args:
        source_id: Source zone_key
        target_id: Target zone_key
    """
    zp_index = build_zone_pairs_index(zone_pairs)

    for dl in discovered_links:
        link_id = get_zone_link_id(dl)
        zp = zp_index.get(link_id)
        if not zp:
            continue

        zp_source_id = zp["source_id"]
        zp_target_id = zp["target_id"]

        # Direct match
        if zp_source_id == source_id and zp_target_id == target_id:
            return True

        # For bidirectional random links, also check reverse
        if (
            zp["type"] == "random"
            and not zp.get("is_one_way", False)
            and zp_source_id == target_id
            and zp_target_id == source_id
        ):
            return True

    return False


def find_zone_pair(zone_pairs: list[dict], source_id: str, target_id: str) -> dict | None:
    """Find a zone pair matching source_id and target_id (in either direction for random links).

    Args:
        zone_pairs: List of zone pairs
        source_id: Source zone_key
        target_id: Target zone_key

    Returns:
        The matching zone pair, or None if not found.
    """
    for pair in zone_pairs:
        pair_source_id = pair["source_id"]
        pair_target_id = pair["target_id"]

        # Check direct match
        if pair_source_id == source_id and pair_target_id == target_id:
            return pair

        # For random links, also check reverse (they're bidirectional)
        if (
            pair["type"] == "random"
            and not pair.get("is_one_way", False)
            and pair_source_id == target_id
            and pair_target_id == source_id
        ):
            return pair

    return None


def find_zone_pair_by_ids(
    zone_pairs: list[dict],
    source_id: str,
    target_id: str,
    source_details: str | None = None,
) -> dict | None:
    """
    Find a zone pair by matching on zone_ids (zone_keys from fog.txt).

    Uses source_details to disambiguate when multiple zone pairs have
    the same source_id and target_id.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        source_id: Zone key for source
        target_id: Zone key for target
        source_details: Optional ASide/BSide text for disambiguation

    Returns:
        The matching zone pair, or None if not found.
    """
    matches = []

    for pair in zone_pairs:
        pair_source_id = pair["source_id"]
        pair_target_id = pair["target_id"]

        # Check direct match
        if pair_source_id == source_id and pair_target_id == target_id:
            matches.append((pair, "direct"))
            continue

        # For random (bidirectional) links, check reverse
        if (
            pair["type"] == "random"
            and not pair.get("is_one_way", False)
            and pair_source_id == target_id
            and pair_target_id == source_id
        ):
            matches.append((pair, "reverse"))

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0][0]

    # Multiple matches - try to disambiguate using source_details
    if source_details:
        for pair, direction in matches:
            if direction == "direct" and pair.get("source_details") == source_details:
                logger.debug(
                    "[MATCH] Disambiguated by source_details: %s -> %s",
                    pair["source"],
                    pair["target"],
                )
                return pair
            if direction == "reverse" and pair.get("target_details") == source_details:
                logger.debug(
                    "[MATCH] Disambiguated by target_details (reverse): %s -> %s",
                    pair["source"],
                    pair["target"],
                )
                return pair

    # Still multiple matches - log warning and return first
    logger.warning(
        "[MATCH] Multiple matches for %s -> %s, returning first (count=%d)",
        source_id,
        target_id,
        len(matches),
    )
    return matches[0][0]


def find_matching_zone_pair_by_ids(
    zone_pairs: list[dict],
    source_candidates: list[tuple[str, str]],
    target_candidates: list[tuple[str, str]],
    source_details: str | None = None,
) -> tuple[str, str, dict] | None:
    """
    Find a matching zone pair using zone_ids from candidate lists.

    Tries all combinations of source and target candidates (using zone_ids)
    until finding a match in zone_pairs.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        source_candidates: List of (zone_id, display_name) for source
        target_candidates: List of (zone_id, display_name) for target
        source_details: Optional ASide/BSide text for disambiguation

    Returns:
        Tuple of (source_id, target_id, zone_pair) if found, None otherwise.
    """
    for source_id, _source_display in source_candidates:
        for target_id, _target_display in target_candidates:
            pair = find_zone_pair_by_ids(zone_pairs, source_id, target_id, source_details)
            if pair:
                logger.debug(
                    "[MATCH] Found pair by ids: '%s' -> '%s' (display: %s -> %s)",
                    source_id,
                    target_id,
                    pair["source"],
                    pair["target"],
                )
                return source_id, target_id, pair

    return None


def find_all_matching_zone_pairs_by_ids(
    zone_pairs: list[dict],
    source_candidates: list[tuple[str, str]],
    target_candidates: list[tuple[str, str]],
    source_details: str | None = None,
) -> list[tuple[str, str, dict]]:
    """
    Find ALL matching zone pairs using zone_ids from candidate lists.

    Unlike find_matching_zone_pair_by_ids which returns the first match,
    this returns all valid combinations. Used when we want to find all possible
    matches and then pick the best one based on additional criteria.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        source_candidates: List of (zone_id, display_name) for source
        target_candidates: List of (zone_id, display_name) for target
        source_details: Optional ASide/BSide text for disambiguation

    Returns:
        List of (source_id, target_id, zone_pair) tuples for all matches.
        Deduplicated by zone_pair ID.
    """
    matches = []
    seen_pair_ids = set()

    for source_id, _source_display in source_candidates:
        for target_id, _target_display in target_candidates:
            pair = find_zone_pair_by_ids(zone_pairs, source_id, target_id, source_details)
            if pair:
                pair_id = pair.get("id")
                if pair_id and pair_id not in seen_pair_ids:
                    seen_pair_ids.add(pair_id)
                    # Return the caller's direction, not the stored direction.
                    # This ensures propagation logic respects the actual travel direction.
                    matches.append((source_id, target_id, pair))
                    logger.debug(
                        "[MATCH] Found pair by ids: '%s' -> '%s' (stored as %s -> %s)",
                        source_id,
                        target_id,
                        pair["source"],
                        pair["target"],
                    )

    return matches


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
        source_candidates: List of (zone_id, display_name) for source, best first
        target_candidates: List of (zone_id, display_name) for target, best first

    Returns:
        Tuple of (source_id, target_id, zone_pair) if found, None otherwise.
    """
    for source_id, _source_display in source_candidates:
        for target_id, _target_display in target_candidates:
            pair = find_zone_pair(zone_pairs, source_id, target_id)
            if pair:
                logger.debug(
                    "[MATCH] Found pair: '%s' → '%s' (display: %s → %s)",
                    source_id,
                    target_id,
                    pair["source"],
                    pair["target"],
                )
                return source_id, target_id, pair

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
        source_candidates: List of (zone_id, display_name) for source
        target_candidates: List of (zone_id, display_name) for target

    Returns:
        List of (source_id, target_id, zone_pair) tuples for all matches.
        Deduplicated by link (A↔B counted once regardless of direction).
    """
    matches = []
    seen_links = set()  # Track unique links to avoid duplicates

    for source_id, _source_display in source_candidates:
        for target_id, _target_display in target_candidates:
            pair = find_zone_pair(zone_pairs, source_id, target_id)
            if pair and pair["type"] == "random":
                # Use frozenset to deduplicate bidirectional links
                link_key = frozenset([pair["source_id"], pair["target_id"]])
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    # Return the caller's direction, not the stored direction.
                    # This ensures propagation logic respects the actual travel direction.
                    matches.append((source_id, target_id, pair))
                    logger.debug(
                        "[MATCH] Found pair: '%s' → '%s' (stored as %s → %s)",
                        source_id,
                        target_id,
                        pair["source"],
                        pair["target"],
                    )

    return matches


def find_candidate_zones(zone_pairs: list[dict], zone_id: str) -> list[dict]:
    """Find all zone pairs that contain a zone_id (for debugging)."""
    candidates = []
    for pair in zone_pairs:
        if pair["source_id"] == zone_id or pair["target_id"] == zone_id:
            candidates.append(pair)
    return candidates


def find_similar_zones(zone_pairs: list[dict], zone_id: str, limit: int = 5) -> list[str]:
    """Find zones with similar zone_ids (for debugging mismatches)."""
    all_zone_ids = set()
    for pair in zone_pairs:
        all_zone_ids.add(pair["source_id"])
        all_zone_ids.add(pair["target_id"])

    # Simple substring matching
    zone_id_lower = zone_id.lower()
    similar = []
    for zid in all_zone_ids:
        if (
            zone_id_lower in zid.lower()
            or zid.lower() in zone_id_lower
            or set(zone_id_lower.split("_")) & set(zid.lower().split("_"))
        ):
            similar.append(zid)

    return similar[:limit]


def compute_total_zones(zone_pairs: list[dict]) -> int:
    """Compute total unique zones from zone pairs (by zone_id)."""
    zone_ids = set()
    for pair in zone_pairs:
        zone_ids.add(pair["source_id"])
        zone_ids.add(pair["target_id"])
    return len(zone_ids)


def compute_discovery_stats(zone_pairs: list[dict], discovered_links: list[dict]) -> dict:
    """
    Compute discovery statistics based on zones (not links).

    Returns:
        dict with:
        - discovered: number of discovered zones
        - total: total number of zones
        - percent: percentage discovered (0-100)
    """
    # Collect all unique zone_ids
    all_zone_ids = set()
    for pair in zone_pairs:
        all_zone_ids.add(pair["source_id"])
        all_zone_ids.add(pair["target_id"])
    total = len(all_zone_ids)

    zp_index = build_zone_pairs_index(zone_pairs)

    # Collect discovered zone_ids (appear in any discovered link)
    discovered_zone_ids = set()
    for link in discovered_links:
        link_id = get_zone_link_id(link)
        zp = zp_index.get(link_id)
        if zp:
            discovered_zone_ids.add(zp["source_id"])
            discovered_zone_ids.add(zp["target_id"])

    # Only count zones that exist in the zone_pairs
    discovered_count = len(discovered_zone_ids & all_zone_ids)

    percent = (discovered_count / total * 100) if total > 0 else 0

    return {
        "discovered": discovered_count,
        "total": total,
        "percent": round(percent, 1),
    }


def get_zones_via_preexisting(zone_pairs: list[dict], start_zone_id: str) -> set[str]:
    """
    Get all zone_ids reachable from start_zone_id via preexisting paths.

    Traverses the preexisting link tree and returns all connected zone_ids,
    including the start zone itself.
    """
    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    visited = {start_zone_id}
    queue = [start_zone_id]

    while queue:
        current = queue.pop(0)
        for neighbor, _is_bidir in preexisting_adj.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return visited


def is_link_discovered(
    discovered_links: list[dict],
    source_id: str,
    target_id: str,
    zone_pairs: list[dict],
) -> bool:
    """Check if a link (in either direction) has been discovered.

    Args:
        source_id: Source zone_key
        target_id: Target zone_key
    """
    zp_index = build_zone_pairs_index(zone_pairs)

    for dl in discovered_links:
        link_id = get_zone_link_id(dl)
        zp = zp_index.get(link_id)
        if zp:
            dl_src_id = zp["source_id"]
            dl_tgt_id = zp["target_id"]
            # Check both directions (random links are bidirectional)
            if (dl_src_id == source_id and dl_tgt_id == target_id) or (
                dl_src_id == target_id and dl_tgt_id == source_id
            ):
                return True
    return False


def is_accessible_from_start(
    discovered_links: list[dict],
    target_zone_id: str,
    zone_pairs: list[dict],
    starting_zone_id: str,
) -> bool:
    """Check if a zone_id is accessible from starting_zone_id via discovered links."""
    if target_zone_id == starting_zone_id:
        return True

    zp_index = build_zone_pairs_index(zone_pairs)

    # Expand links to (source_id, target_id) tuples
    expanded_links = []
    for dl in discovered_links:
        link_id = get_zone_link_id(dl)
        zp = zp_index.get(link_id)
        if zp:
            expanded_links.append((zp["source_id"], zp["target_id"]))

    # BFS through discovered links
    visited = {starting_zone_id}
    queue = [starting_zone_id]

    while queue:
        current = queue.pop(0)
        for src_id, tgt_id in expanded_links:
            neighbor = None

            # Can traverse in either direction (discovered links are bidirectional)
            if src_id == current and tgt_id not in visited:
                neighbor = tgt_id
            elif tgt_id == current and src_id not in visited:
                neighbor = src_id

            if neighbor:
                if neighbor == target_zone_id:
                    return True
                visited.add(neighbor)
                queue.append(neighbor)

    return False


def find_path_prioritizing_discovered(
    zone_pairs: list[dict],
    discovered_links: list[dict],
    target_zone_id: str,
    starting_zone_id: str,
) -> list[tuple[str, str]]:
    """
    Find the shortest path from starting_zone_id to target_zone_id, prioritizing discovered nodes.

    Uses a modified BFS that explores discovered nodes first at each level.
    This ensures the path passes through as many already-discovered nodes as possible.

    Returns:
        List of (source_id, target_id) tuples representing the links on the path.
        Empty list if no path exists or if target is starting_zone_id.
    """
    if target_zone_id == starting_zone_id:
        return []

    full_adj = build_full_adjacency(zone_pairs)
    discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs, starting_zone_id)

    # BFS with priority for discovered nodes
    # Each entry: (current_zone_id, path_so_far)
    # path_so_far is a list of (source_id, target_id) tuples
    visited = {starting_zone_id}
    queue = [(starting_zone_id, [])]

    while queue:
        current, path = queue.pop(0)

        # Get neighbors and split into discovered/undiscovered
        neighbors = full_adj.get(current, [])
        discovered_neighbors = []
        undiscovered_neighbors = []

        for dest, _is_bidir, pair in neighbors:
            if dest in visited:
                continue

            # Determine the link direction for recording (using zone_ids)
            pair_source_id = pair["source_id"]
            pair_target_id = pair["target_id"]
            if pair_source_id == current:
                link = (current, pair_target_id)
            else:
                link = (current, pair_source_id)

            if dest in discovered_nodes:
                discovered_neighbors.append((dest, link))
            else:
                undiscovered_neighbors.append((dest, link))

        # Process discovered neighbors first (they stay at the front of the queue)
        for dest, link in discovered_neighbors + undiscovered_neighbors:
            new_path = path + [link]

            if dest == target_zone_id:
                return new_path

            visited.add(dest)
            # Insert discovered neighbors at front to prioritize them
            if dest in discovered_nodes:
                queue.insert(0, (dest, new_path))
            else:
                queue.append((dest, new_path))

    return []  # No path found


def compute_backprop_cost(
    zone_pairs: list[dict],
    discovered_links: list[dict],
    source_zone_id: str,
    starting_zone_id: str,
) -> int:
    """
    Compute the back-propagation cost to make source_zone_id accessible from starting_zone_id.

    The cost is the number of RANDOM (not preexisting) links that would need to be
    back-propagated to create a path from starting_zone_id to source_zone_id.

    Preexisting links don't count because they represent vanilla connections that
    are automatically discovered when reaching a zone.

    Args:
        zone_pairs: List of zone pairs from the spoiler log
        discovered_links: Currently discovered links
        source_zone_id: The zone_id we want to reach
        starting_zone_id: The starting zone_id

    Returns:
        Number of random links needed. 0 if already accessible. -1 if unreachable.
    """
    # If already accessible, no back-propagation needed
    if is_accessible_from_start(discovered_links, source_zone_id, zone_pairs, starting_zone_id):
        return 0

    # Find path from starting_zone_id to source
    path = find_path_prioritizing_discovered(
        zone_pairs, discovered_links, source_zone_id, starting_zone_id
    )
    if not path:
        return -1  # Unreachable

    # Build index to look up link type (keyed by zone_ids)
    zp_by_endpoints: dict[tuple[str, str], str] = {}
    for zp in zone_pairs:
        src_id = zp["source_id"]
        tgt_id = zp["target_id"]
        zp_by_endpoints[(src_id, tgt_id)] = zp["type"]
        # Also index reverse for bidirectional lookup
        zp_by_endpoints[(tgt_id, src_id)] = zp["type"]

    # Count random links in path
    random_count = 0
    for src, dst in path:
        link_type = zp_by_endpoints.get((src, dst))
        if link_type == "random":
            random_count += 1

    return random_count


def find_reachable_nodes(
    discovered_links: list[dict],
    zone_pairs: list[dict],
    starting_zone_id: str,
) -> set[str]:
    """
    Find all zone_ids reachable from starting_zone_id via discovered links.
    Uses BFS through the discovered link graph.
    """
    reachable = {starting_zone_id}
    queue = [starting_zone_id]

    zp_index = build_zone_pairs_index(zone_pairs)

    # Expand links to (source_id, target_id) tuples
    expanded_links = []
    for dl in discovered_links:
        link_id = get_zone_link_id(dl)
        zp = zp_index.get(link_id)
        if zp:
            expanded_links.append((zp["source_id"], zp["target_id"]))

    while queue:
        current = queue.pop(0)
        for src_id, tgt_id in expanded_links:
            neighbor = None

            # Can traverse in either direction (discovered links are bidirectional)
            if src_id == current and tgt_id not in reachable:
                neighbor = tgt_id
            elif tgt_id == current and src_id not in reachable:
                neighbor = src_id

            if neighbor:
                reachable.add(neighbor)
                queue.append(neighbor)

    return reachable


def undiscover_zone(
    discovered_links: list[dict],
    zone_id_to_remove: str,
    zone_pairs: list[dict],
    starting_zone_id: str,
) -> tuple[list[dict], list[str]]:
    """
    Undiscover a zone and all zones that become unreachable from starting_zone_id.

    Args:
        discovered_links: Current list of discovered links
        zone_id_to_remove: The zone_id to undiscover
        zone_pairs: Zone pairs for expanding link_ids
        starting_zone_id: The starting zone_id

    Returns:
        Tuple of (new_discovered_links, removed_zone_ids)
    """
    if zone_id_to_remove == starting_zone_id:
        return discovered_links, []

    zp_index = build_zone_pairs_index(zone_pairs)

    def get_link_endpoint_ids(dl: dict) -> tuple[str, str]:
        """Get source_id and target_id from a discovered link."""
        link_id = get_zone_link_id(dl)
        zp = zp_index.get(link_id)
        if zp:
            return zp.get("source_id", ""), zp.get("target_id", "")
        return "", ""

    # First, remove all links involving the zone to remove
    filtered_links = []
    for dl in discovered_links:
        src_id, tgt_id = get_link_endpoint_ids(dl)
        if src_id != zone_id_to_remove and tgt_id != zone_id_to_remove:
            filtered_links.append(dl)

    # Find all zones that are still reachable from starting_zone_id
    reachable = find_reachable_nodes(filtered_links, zone_pairs, starting_zone_id)

    # Get zones that were discovered before
    previously_discovered = get_discovered_nodes(discovered_links, zone_pairs, starting_zone_id)

    # Find zones that became unreachable (cascade undiscovery)
    removed_zone_ids = previously_discovered - reachable

    # Remove all links involving unreachable zones
    final_links = []
    for dl in filtered_links:
        src_id, tgt_id = get_link_endpoint_ids(dl)
        if src_id in reachable and tgt_id in reachable:
            final_links.append(dl)

    return final_links, list(removed_zone_ids)


def compute_zone_exits(
    zone_pairs: list[dict],
    discovered_links: list[dict],
    current_zone_id: str,
) -> list[dict]:
    """
    Compute all fog gate exits accessible from a zone.

    Traverses preexisting paths to find all "merged" zones, then lists
    all random links exiting from those zones.

    Args:
        zone_pairs: The spoiler log zone pairs
        discovered_links: Currently discovered links
        current_zone_id: The zone_id the player is currently in

    Returns:
        List of exits, each with:
        - target: zone display name if discovered, "???" otherwise
        - target_id: zone_id of target (for internal use)
        - description: how to get there (from source_details or target_details)
        - from_zone: display name of which zone (in the preexisting group) this exit is from
        - from_zone_id: zone_id of from_zone
    """
    # Get all zone_ids reachable via preexisting paths
    merged_zone_ids = get_zones_via_preexisting(zone_pairs, current_zone_id)

    exits = []
    seen_link_ids = set()  # Deduplicate by link ID

    for pair in zone_pairs:
        if pair["type"] != "random":
            continue

        pair_source_id = pair["source_id"]
        pair_target_id = pair["target_id"]
        pair_source_name = pair["source"]
        pair_target_name = pair["target"]
        pair_id = pair.get("id")

        # Check if this link exits from one of our merged zones
        from_zone_id = None
        from_zone_name = None
        to_zone_id = None
        to_zone_name = None
        description = None

        is_one_way_link = pair.get("is_one_way", False)

        if pair_source_id in merged_zone_ids:
            from_zone_id = pair_source_id
            from_zone_name = pair_source_name
            to_zone_id = pair_target_id
            to_zone_name = pair_target_name
            # When exiting from source, use source_details as description
            description = pair.get("source_details") or ""
        elif pair_target_id in merged_zone_ids and not is_one_way_link:
            # Bidirectional random links can be exited from target side too
            from_zone_id = pair_target_id
            from_zone_name = pair_target_name
            to_zone_id = pair_source_id
            to_zone_name = pair_source_name
            # When exiting from target side, use target_details as description
            description = pair.get("target_details") or ""
        else:
            continue

        # Deduplicate by link ID (each zone_pair is unique, even with same endpoints)
        if pair_id:
            if pair_id in seen_link_ids:
                continue
            seen_link_ids.add(pair_id)

        # NOTE: We intentionally do NOT skip random links where to_zone is in merged_zone_ids.
        # Random links represent randomized fog gate destinations and should always be shown.
        # Even if the target zone is reachable via preexisting (e.g., dropping down), the
        # fog gate may have been randomized to go there, and players need to know about it.
        # The "skip internal links" logic was removed to fix parallel link display issues.

        # Check if this link has been discovered
        discovered = is_link_discovered(
            discovered_links, pair_source_id, pair_target_id, zone_pairs
        )

        exits.append(
            {
                "id": pair_id,  # Include link ID in response
                "target": to_zone_name if discovered else "???",
                "target_id": to_zone_id,
                "description": description,
                "from_zone": from_zone_name if from_zone_id != current_zone_id else None,
                "from_zone_id": from_zone_id if from_zone_id != current_zone_id else None,
            }
        )

    return exits


def get_zone_scaling(zones: dict[str, dict] | None, zone_id: str) -> str | None:
    """
    Get the scaling text for a zone by its zone_key.

    Args:
        zones: Zone metadata dict keyed by zone_id (zone_key)
        zone_id: The zone_key of the zone to look up

    Returns:
        The scaling text (e.g., "Scaling: tier 1, previously 2") or None if not found.
    """
    if not zones:
        return None

    zone = zones.get(zone_id)
    if zone:
        return zone.get("scaling")

    return None
