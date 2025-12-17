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


def build_full_adjacency(
    zone_pairs: list[dict],
) -> dict[str, list[tuple[str, bool, dict]]]:
    """
    Build adjacency list for ALL links (random and preexisting).
    Returns dict[source] -> list of (destination, is_bidirectional, pair)

    Random links are bidirectional UNLESS marked as inherently one-way
    (e.g., sending gates, abductions).
    Preexisting links are bidirectional only if a reverse link exists.
    """
    adj: dict[str, list[tuple[str, bool, dict]]] = defaultdict(list)

    for pair in zone_pairs:
        source = pair["source"]
        dest = pair["destination"]

        if pair["type"] == "random":
            # Random links are bidirectional UNLESS marked as inherently one-way
            is_bidir = not pair.get("is_inherently_one_way", False)
            adj[source].append((dest, is_bidir, pair))
            if is_bidir:
                adj[dest].append((source, True, pair))
        else:
            # Preexisting links: one-way unless reverse exists
            is_bidir = not is_one_way(pair, zone_pairs)
            adj[source].append((dest, is_bidir, pair))
            if is_bidir:
                adj[dest].append((source, True, pair))

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


def compute_discovery_stats(zone_pairs: list[dict], discovered_links: list[dict]) -> dict:
    """
    Compute discovery statistics based on zones (not links).

    Returns:
        dict with:
        - discovered: number of discovered zones
        - total: total number of zones
        - percent: percentage discovered (0-100)
    """
    # Collect all unique zones
    all_zones = set()
    for pair in zone_pairs:
        all_zones.add(pair["source"])
        all_zones.add(pair["destination"])
    total = len(all_zones)

    # Collect discovered zones (appear in any discovered link)
    discovered_zones = set()
    for link in discovered_links:
        discovered_zones.add(link["source"])
        discovered_zones.add(link["target"])

    # Only count zones that exist in the zone_pairs
    discovered_count = len(discovered_zones & all_zones)

    percent = (discovered_count / total * 100) if total > 0 else 0

    return {
        "discovered": discovered_count,
        "total": total,
        "percent": round(percent, 1),
    }


def get_zones_via_preexisting(zone_pairs: list[dict], start_zone: str) -> set[str]:
    """
    Get all zones reachable from start_zone via preexisting paths.

    Traverses the preexisting link tree and returns all connected zones,
    including the start zone itself.
    """
    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    visited = {start_zone}
    queue = [start_zone]

    while queue:
        current = queue.pop(0)
        for neighbor, _is_bidir in preexisting_adj.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return visited


def is_link_discovered(discovered_links: list[dict], source: str, target: str) -> bool:
    """Check if a link (in either direction) has been discovered."""
    for dl in discovered_links:
        dl_src = dl.get("source", "")
        dl_tgt = dl.get("target", "")
        # Check both directions (random links are bidirectional)
        if (names_match(dl_src, source) and names_match(dl_tgt, target)) or (
            names_match(dl_src, target) and names_match(dl_tgt, source)
        ):
            return True
    return False


def is_accessible_from_start(
    discovered_links: list[dict],
    target_node: str,
) -> bool:
    """
    Check if a node is accessible from START_NODE via discovered links.
    """
    if target_node == START_NODE:
        return True

    # BFS through discovered links
    visited = {START_NODE}
    queue = [START_NODE]

    while queue:
        current = queue.pop(0)
        for dl in discovered_links:
            src = dl.get("source", "")
            tgt = dl.get("target", "")
            neighbor = None

            # Can traverse in either direction (discovered links are bidirectional)
            if src == current and tgt not in visited:
                neighbor = tgt
            elif tgt == current and src not in visited:
                neighbor = src

            if neighbor:
                if neighbor == target_node:
                    return True
                visited.add(neighbor)
                queue.append(neighbor)

    return False


def find_path_prioritizing_discovered(
    zone_pairs: list[dict],
    discovered_links: list[dict],
    target_node: str,
) -> list[tuple[str, str]]:
    """
    Find the shortest path from START_NODE to target_node, prioritizing discovered nodes.

    Uses a modified BFS that explores discovered nodes first at each level.
    This ensures the path passes through as many already-discovered nodes as possible.

    Returns:
        List of (source, target) tuples representing the links on the path.
        Empty list if no path exists or if target is START_NODE.
    """
    if target_node == START_NODE:
        return []

    full_adj = build_full_adjacency(zone_pairs)
    discovered_nodes = get_discovered_nodes(discovered_links)

    # BFS with priority for discovered nodes
    # Each entry: (current_node, path_so_far)
    # path_so_far is a list of (source, target) tuples
    visited = {START_NODE}
    queue = [(START_NODE, [])]

    while queue:
        current, path = queue.pop(0)

        # Get neighbors and split into discovered/undiscovered
        neighbors = full_adj.get(current, [])
        discovered_neighbors = []
        undiscovered_neighbors = []

        for dest, _is_bidir, pair in neighbors:
            if dest in visited:
                continue

            # Determine the link direction for recording
            if pair["source"] == current:
                link = (current, pair["destination"])
            else:
                link = (current, pair["source"])

            if dest in discovered_nodes:
                discovered_neighbors.append((dest, link))
            else:
                undiscovered_neighbors.append((dest, link))

        # Process discovered neighbors first (they stay at the front of the queue)
        for dest, link in discovered_neighbors + undiscovered_neighbors:
            new_path = path + [link]

            if dest == target_node:
                return new_path

            visited.add(dest)
            # Insert discovered neighbors at front to prioritize them
            if dest in discovered_nodes:
                queue.insert(0, (dest, new_path))
            else:
                queue.append((dest, new_path))

    return []  # No path found


def find_reachable_nodes(discovered_links: list[dict]) -> set[str]:
    """
    Find all nodes reachable from START_NODE via discovered links.
    Uses BFS through the discovered link graph.
    """
    reachable = {START_NODE}
    queue = [START_NODE]

    while queue:
        current = queue.pop(0)
        for dl in discovered_links:
            src = dl.get("source", "")
            tgt = dl.get("target", "")
            neighbor = None

            # Can traverse in either direction (discovered links are bidirectional)
            if src == current and tgt not in reachable:
                neighbor = tgt
            elif tgt == current and src not in reachable:
                neighbor = src

            if neighbor:
                reachable.add(neighbor)
                queue.append(neighbor)

    return reachable


def undiscover_zone(
    discovered_links: list[dict],
    zone_to_remove: str,
) -> tuple[list[dict], list[str]]:
    """
    Undiscover a zone and all zones that become unreachable from START.

    Args:
        discovered_links: Current list of discovered links
        zone_to_remove: The zone to undiscover

    Returns:
        Tuple of (new_discovered_links, removed_zones)
    """
    if zone_to_remove == START_NODE:
        return discovered_links, []

    # First, remove all links involving the zone to remove
    filtered_links = [
        dl
        for dl in discovered_links
        if dl.get("source") != zone_to_remove and dl.get("target") != zone_to_remove
    ]

    # Find all zones that are still reachable from START
    reachable = find_reachable_nodes(filtered_links)

    # Get zones that were discovered before
    previously_discovered = get_discovered_nodes(discovered_links)

    # Find zones that became unreachable (cascade undiscovery)
    removed_zones = previously_discovered - reachable

    # Remove all links involving unreachable zones
    final_links = [
        dl
        for dl in filtered_links
        if dl.get("source") in reachable and dl.get("target") in reachable
    ]

    return final_links, list(removed_zones)


def compute_zone_exits(
    zone_pairs: list[dict],
    discovered_links: list[dict],
    current_zone: str,
) -> list[dict]:
    """
    Compute all fog gate exits accessible from a zone.

    Traverses preexisting paths to find all "merged" zones, then lists
    all random links exiting from those zones.

    Args:
        zone_pairs: The spoiler log zone pairs
        discovered_links: Currently discovered links
        current_zone: The zone the player is currently in

    Returns:
        List of exits, each with:
        - destination: zone name if discovered, "???" otherwise
        - description: how to get there (from source_details or target_details)
        - from_zone: which zone (in the preexisting group) this exit is from
    """
    # Get all zones reachable via preexisting paths
    merged_zones = get_zones_via_preexisting(zone_pairs, current_zone)

    exits = []
    seen_links = set()  # Deduplicate bidirectional links

    for pair in zone_pairs:
        if pair["type"] != "random":
            continue

        pair_source = pair["source"]
        pair_target = pair["destination"]

        # Check if this link exits from one of our merged zones
        from_zone = None
        to_zone = None
        description = None

        is_one_way_link = pair.get("is_inherently_one_way", False)

        if pair_source in merged_zones:
            from_zone = pair_source
            to_zone = pair_target
            # When exiting from source, use source_details as description
            description = pair.get("source_details") or ""
        elif pair_target in merged_zones and not is_one_way_link:
            # Bidirectional random links can be exited from target side too
            from_zone = pair_target
            to_zone = pair_source
            # When exiting from target side, use target_details as description
            description = pair.get("target_details") or ""
        else:
            continue

        # Deduplicate (A↔B is one link)
        link_key = frozenset([pair_source, pair_target])
        if link_key in seen_links:
            continue
        seen_links.add(link_key)

        # Check if destination is in the same merged group (skip internal links)
        if to_zone in merged_zones:
            continue

        # Check if this link has been discovered
        discovered = is_link_discovered(discovered_links, pair_source, pair_target)

        exits.append(
            {
                "destination": to_zone if discovered else "???",
                "description": description,
                "from_zone": from_zone if from_zone != current_zone else None,
            }
        )

    return exits
