"""
Game logic: discovery propagation through preexisting links.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from fogtracker.database import Game
from fogtracker.zone_matching import (
    build_preexisting_adjacency,
    find_candidate_zones,
    find_path_prioritizing_discovered,
    find_similar_zones,
    find_zone_pair,
    get_discovered_nodes,
    get_zone_link_id,
    is_accessible_from_start,
    link_exists,
)

logger = logging.getLogger(__name__)


# Re-export commonly used functions for backward compatibility
from fogtracker.zone_matching import (  # noqa: E402, F401
    compute_discovery_stats,
    compute_total_zones,
    find_all_matching_zone_pairs,
    find_matching_zone_pair,
    names_match,
    strip_parenthetical,
)


@dataclass
class DiscoveredLink:
    """A discovered link with its metadata."""

    source_name: str
    target_name: str
    link_type: str  # "random" or "preexisting"
    source_id: str | None = None
    target_id: str | None = None

    def __post_init__(self) -> None:
        if self.source_id is None:
            self.source_id = self.source_name
        if self.target_id is None:
            self.target_id = self.target_name


@dataclass
class DiscoveryResult:
    """Structured result of a discovery propagation."""

    origin: str  # The zone where the player was when discovering
    main_links: list[DiscoveredLink] = field(
        default_factory=list
    )  # The directly discovered link(s)
    backprop_links: list[DiscoveredLink] = field(
        default_factory=list
    )  # Links discovered via back-propagation
    forward_links: list[DiscoveredLink] = field(
        default_factory=list
    )  # Links discovered via forward-propagation

    def all_links(self) -> list[dict[str, str]]:
        """Return all links as a flat list for outbound payloads."""
        result = []
        for link in self.backprop_links + self.main_links + self.forward_links:
            result.append(
                {
                    "source_name": link.source_name,
                    "source_id": link.source_id,
                    "target_name": link.target_name,
                    "target_id": link.target_id,
                }
            )
        return result

    def total_count(self) -> int:
        """Return total number of newly discovered links."""
        return len(self.backprop_links) + len(self.main_links) + len(self.forward_links)


def format_discovery_summary(
    result: DiscoveryResult,
    discovered_by: str,
    total_discovered: int | None = None,
    total_links: int | None = None,
    warp_type: str | None = None,
    resolution_method: str | None = None,
) -> str:
    """Format a discovery result as a visual summary for logging."""
    lines = []

    # Header
    lines.append("╭─ Discovery Summary ─────────────────────────────────────────")
    lines.append(f"│ Origin:     {result.origin}")
    if warp_type:
        lines.append(f"│ Warp type:  {warp_type}")
    if resolution_method:
        lines.append(f"│ Resolved:   {resolution_method}")

    # Main discovered link(s)
    if result.main_links:
        for link in result.main_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│ Link:       {link.source_name} {arrow} {link.target_name}")

    # Back-propagation section
    if result.backprop_links:
        lines.append(f"├─ Back-propagation ({len(result.backprop_links)}):")
        for link in result.backprop_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│   ◂ {link.source_name} {arrow} {link.target_name}")

    # Forward-propagation section
    if result.forward_links:
        lines.append(f"├─ Forward-propagation ({len(result.forward_links)}):")
        for link in result.forward_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│   ▸ {link.source_name} {arrow} {link.target_name}")

    # Footer with stats
    total = result.total_count()
    link_word = "link" if total == 1 else "links"
    footer = f"╰─ Total: {total} new {link_word}"
    if total_discovered is not None and total_links is not None:
        percent = (total_discovered / total_links * 100) if total_links > 0 else 0
        footer += f" │ Progress: {total_discovered}/{total_links} ({percent:.1f}%)"
    lines.append(footer)

    return "\n".join(lines)


def format_ingame_display(
    current_zone: str,
    exits: list[dict],
    stats: dict,
) -> str:
    """Format what will be displayed in-game by the mod overlay."""
    lines = []

    # Header: Zone Name • discovered/total
    lines.append("╭─ In-game Display ────────────────────────────────────────────")
    stats_str = f"{stats.get('discovered', 0)}/{stats.get('total', 0)}"
    lines.append(f"│ {current_zone} • {stats_str}")

    # Exits
    if exits:
        lines.append("├─ Exits:")
        for exit_info in exits:
            target = exit_info.get("target", "???")
            from_zone = exit_info.get("from_zone")
            description = exit_info.get("description", "")

            # Format: → Target [from Zone]
            exit_line = f"→ {target}"
            if from_zone:
                exit_line += f" [from {from_zone}]"
            lines.append(f"│   {exit_line}")

            # Description (indented)
            if description:
                lines.append(f"│     {description}")
    else:
        lines.append("│ No exits available")

    lines.append("╰──────────────────────────────────────────────────────────────")

    return "\n".join(lines)


def format_zone_resolution(
    zone: str,
    method: str,
    exits_count: int,
    stats: dict,
    grace_entity_id: int | None = None,
) -> str:
    """Format a zone resolution result as a visual summary for logging."""
    lines = []

    # Header
    lines.append("╭─ Zone Resolution ───────────────────────────────────────────")
    lines.append(f"│ Zone:       {zone}")
    lines.append(f"│ Method:     {method}")
    if grace_entity_id:
        lines.append(f"│ Grace ID:   {grace_entity_id}")

    # Footer with stats
    stats_str = f"{stats.get('discovered', 0)}/{stats.get('total', 0)}"
    lines.append(f"╰─ Exits: {exits_count} │ Progress: {stats_str}")

    return "\n".join(lines)


def format_resolution_failure(
    context: str,
    map_id: str,
    reason: str,
    candidates: list[str] | None = None,
) -> str:
    """Format a resolution failure as a visual warning for logging."""
    lines = []

    # Header
    lines.append("╭─ Resolution Failed ─────────────────────────────────────────")
    lines.append(f"│ Context:    {context}")
    lines.append(f"│ Map:        {map_id}")
    lines.append(f"│ Reason:     {reason}")

    if candidates:
        lines.append("├─ Candidates tried:")
        for c in candidates:
            lines.append(f"│   • {c}")

    lines.append("╰──────────────────────────────────────────────────────────────")

    return "\n".join(lines)


def format_undiscovery_summary(
    target_zone: str,
    removed_zones: list[str],
    total_discovered: int | None = None,
    total_links: int | None = None,
) -> str:
    """Format an undiscovery result as a visual summary for logging."""
    lines = []

    # Header
    lines.append("╭─ Undiscovery Summary ───────────────────────────────────────")
    lines.append(f"│ Target:     {target_zone}")

    # Cascade section (other zones that became unreachable)
    cascade_zones = [z for z in removed_zones if z != target_zone]
    if cascade_zones:
        lines.append(f"├─ Cascade ({len(cascade_zones)}):")
        for zone in cascade_zones:
            lines.append(f"│   ✗ {zone}")

    # Footer with stats
    total = len(removed_zones)
    zone_word = "zone" if total == 1 else "zones"
    footer = f"╰─ Total: {total} {zone_word} removed"
    if total_discovered is not None and total_links is not None:
        percent = (total_discovered / total_links * 100) if total_links > 0 else 0
        footer += f" │ Progress: {total_discovered}/{total_links} ({percent:.1f}%)"
    lines.append(footer)

    return "\n".join(lines)


async def propagate_discovery(
    db: AsyncSession,
    game_id: UUID,
    source_id: str,
    target_id: str,
    discovered_by: str = "mod",
    link_id: str | None = None,
) -> DiscoveryResult:
    """
    Propagate a discovery through preexisting links.
    Returns a DiscoveryResult with categorized newly discovered links.

    Args:
        source_id: Source zone_key
        target_id: Target zone_key

    Logic:
    1. Record the initial link as discovered
    2. If target was not previously discovered, find all preexisting links
       from target to already-discovered nodes and record them
    3. Recursively propagate through newly reachable preexisting links
    """
    logger.debug("[DISCOVERY] Request: '%s' → '%s' (by %s)", source_id, target_id, discovered_by)

    # Initialize result with origin (using zone_id)
    discovery_result = DiscoveryResult(origin=source_id)

    # Get game data - refresh to ensure we see latest changes from other calls
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if not game:
        logger.warning("[DISCOVERY] Game %s not found", game_id)
        return discovery_result

    # Force refresh to get latest discovered_zone_links from DB
    await db.refresh(game, ["discovered_zone_links"])

    logger.debug(
        "[DISCOVERY] Starting with %d discovered links",
        len(game.discovered_zone_links) if game.discovered_zone_links else 0,
    )

    zone_pairs = game.zone_links
    if not zone_pairs:
        logger.warning("[DISCOVERY] Game %s has no zone_links", game_id)
        return discovery_result

    # Get starting_zone_id from game (default to chapel_start for backward compat)
    starting_zone_id = game.starting_zone_id or "chapel_start"

    # Build a lookup from zone_id to display name (from zone_links)
    zone_name_by_id: dict[str, str] = {}
    for pair in zone_pairs:
        src_id = pair.get("source_id")
        src_name = pair.get("source")
        if src_id and src_name and src_id not in zone_name_by_id:
            zone_name_by_id[src_id] = src_name
        dst_id = pair.get("target_id")
        dst_name = pair.get("target")
        if dst_id and dst_name and dst_id not in zone_name_by_id:
            zone_name_by_id[dst_id] = dst_name

    def get_zone_name(zone_id: str) -> str:
        return zone_name_by_id.get(zone_id, zone_id)

    discovery_result.origin = get_zone_name(source_id)

    # Build index to look up link type by zone_ids (source_id/target_id)
    def get_link_type(src_id: str, dst_id: str) -> str:
        """Get the type of a link (random or preexisting) by zone_ids."""
        for zp in zone_pairs:
            zp_src = zp["source_id"]
            zp_dst = zp["target_id"]
            if (zp_src == src_id and zp_dst == dst_id) or (zp_src == dst_id and zp_dst == src_id):
                return zp.get("type", "random")
        return "random"

    # Check if the link exists in zone_links (using zone_ids)
    found_pair = find_zone_pair(zone_pairs, source_id, target_id)
    main_link_type = "random"
    if found_pair:
        main_link_type = found_pair.get("type", "random")
        # Note: We keep the caller's source/target direction for propagation logic.
        # The pair may be stored in either direction, but we respect the user's intent
        # (e.g., clicking "A → B" should treat A as accessible, not B).
        # The zone_link_id lookup handles both directions.
        logger.debug(
            "[DISCOVERY] Found matching pair: %s → %s (type=%s, stored as %s → %s)",
            source_id,
            target_id,
            main_link_type,
            found_pair["source_id"],
            found_pair["target_id"],
        )
    else:
        logger.warning("[DISCOVERY] No matching pair found for '%s' → '%s'", source_id, target_id)

        # Log candidates for source zone (using zone_ids)
        source_candidates = find_candidate_zones(zone_pairs, source_id)
        if source_candidates:
            logger.debug(
                "[DISCOVERY] Source '%s' found in %d pairs: %s",
                source_id,
                len(source_candidates),
                [(c["source_id"], c["target_id"]) for c in source_candidates[:5]],
            )
        else:
            similar_source = find_similar_zones(zone_pairs, source_id)
            if similar_source:
                logger.debug(
                    "[DISCOVERY] Similar zones to source '%s': %s", source_id, similar_source
                )
            else:
                logger.debug("[DISCOVERY] Source '%s' not found in any zone pair", source_id)

        # Log candidates for target zone (using zone_ids)
        target_candidates = find_candidate_zones(zone_pairs, target_id)
        if target_candidates:
            logger.debug(
                "[DISCOVERY] Target '%s' found in %d pairs: %s",
                target_id,
                len(target_candidates),
                [(c["source_id"], c["target_id"]) for c in target_candidates[:5]],
            )
        else:
            similar_target = find_similar_zones(zone_pairs, target_id)
            if similar_target:
                logger.debug(
                    "[DISCOVERY] Similar zones to target '%s': %s", target_id, similar_target
                )
            else:
                logger.debug("[DISCOVERY] Target '%s' not found in any zone pair", target_id)

    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    # Build index for finding zone_link_id by zone_ids (source_id/target_id)
    zp_by_endpoints: dict[tuple[str, str], str] = {}
    for zp in zone_pairs:
        zp_id = zp.get("id")
        if zp_id:
            zp_by_endpoints[(zp["source_id"], zp["target_id"])] = zp_id

    def find_zone_link_id(src_id: str, dst_id: str) -> str | None:
        """Find zone_link ID for a source_id/target_id pair."""
        return zp_by_endpoints.get((src_id, dst_id)) or zp_by_endpoints.get((dst_id, src_id))

    # Get current discovered links (make a mutable copy)
    discovered_links: list[dict] = (
        list(game.discovered_zone_links) if game.discovered_zone_links else []
    )

    # Get current discovered nodes (using starting_zone_id)
    discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs, starting_zone_id)
    logger.debug("[DISCOVERY] Currently %d discovered nodes", len(discovered_nodes))

    now = datetime.now(UTC).isoformat()

    # Track zones newly discovered via back-propagation (need to propagate their preexisting)
    backprop_new_zones: set[str] = set()

    # Back-propagation: if source is not accessible from START, find path and discover it
    if not is_accessible_from_start(discovered_links, source_id, zone_pairs, starting_zone_id):
        logger.debug(
            "[DISCOVERY] Source '%s' not accessible from START, back-propagating", source_id
        )
        path_to_source = find_path_prioritizing_discovered(
            zone_pairs, discovered_links, source_id, starting_zone_id
        )
        if path_to_source:
            logger.debug("[DISCOVERY] Back-propagation path: %s", path_to_source)
            for src, dst in path_to_source:
                if not link_exists(discovered_links, src, dst, zone_pairs):
                    backprop_zone_link_id = find_zone_link_id(src, dst)
                    if backprop_zone_link_id:
                        new_link = {
                            "zone_link_id": backprop_zone_link_id,
                            "discovered_at": now,
                            "discovered_by": f"{discovered_by} (backprop)",
                        }
                        discovered_links.append(new_link)
                        link_type = get_link_type(src, dst)
                        discovery_result.backprop_links.append(
                            DiscoveredLink(
                                source_id=src,
                                source_name=get_zone_name(src),
                                target_id=dst,
                                target_name=get_zone_name(dst),
                                link_type=link_type,
                            )
                        )
                        logger.debug(
                            "[DISCOVERY] Back-propagated link: %s → %s (id=%s, type=%s)",
                            src,
                            dst,
                            backprop_zone_link_id,
                            link_type,
                        )
                    else:
                        logger.warning("[DISCOVERY] No zone_link_id found for %s → %s", src, dst)
            # Update discovered nodes after back-propagation
            discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs, starting_zone_id)

            # Collect zones newly discovered via back-propagation
            # These zones need their preexisting links propagated
            for _src, dst in path_to_source:
                backprop_new_zones.add(dst)
            # The source itself is also newly accessible
            backprop_new_zones.add(source_id)
            logger.debug("[DISCOVERY] Zones newly accessible via backprop: %s", backprop_new_zones)
        else:
            logger.warning("[DISCOVERY] No path found from START to '%s'", source_id)

    # Build index for looking up ALL links between two zones (not just one direction)
    def find_all_zone_link_ids(src_id: str, dst_id: str) -> list[tuple[str, str]]:
        """Find all zone_link IDs for links between src_id and dst_id (both directions)."""
        results = []
        for zp in zone_pairs:
            zp_id = zp.get("id")
            if not zp_id:
                continue
            zp_src = zp["source_id"]
            zp_dst = zp["target_id"]
            # Match either direction
            if (zp_src == src_id and zp_dst == dst_id) or (zp_src == dst_id and zp_dst == src_id):
                results.append((zp_id, zp["type"]))
        return results

    # BFS through preexisting links
    # For the initial link, use provided link_id if available
    # Mark the initial link specially so we can identify it
    # Tuple: (source, target, link_id, is_main_link, blocks_propagation)
    main_blocks_propagation = found_pair.get("blocks_propagation", False) if found_pair else False
    queue: list[tuple[str, str, str | None, bool, bool]] = [
        (source_id, target_id, link_id, True, main_blocks_propagation)
    ]
    visited: set[tuple[str, str]] = set()

    # Also queue preexisting links from zones newly discovered via back-propagation
    # These zones are now accessible but their preexisting links haven't been propagated
    for zone in backprop_new_zones:
        for next_dst, _is_bidir in preexisting_adj.get(zone, []):
            queue.append((zone, next_dst, None, False, False))
            logger.debug(
                "[DISCOVERY] Queuing preexisting from backprop zone: %s → %s", zone, next_dst
            )

    while queue:
        src, dst, provided_link_id, is_main_link, blocks_prop = queue.pop(0)
        link_key = (src, dst)

        if link_key in visited:
            continue
        visited.add(link_key)

        # Record this link as discovered (if not already)
        if not link_exists(discovered_links, src, dst, zone_pairs):
            # Use provided zone_link_id if available, otherwise find it
            resolved_zone_link_id = provided_link_id or find_zone_link_id(src, dst)
            if resolved_zone_link_id:
                new_link = {
                    "zone_link_id": resolved_zone_link_id,
                    "discovered_at": now,
                    "discovered_by": discovered_by,
                }
                discovered_links.append(new_link)
                link_type = get_link_type(src, dst)

                # Categorize the link
                if is_main_link:
                    discovery_result.main_links.append(
                        DiscoveredLink(
                            source_id=src,
                            source_name=get_zone_name(src),
                            target_id=dst,
                            target_name=get_zone_name(dst),
                            link_type=link_type,
                        )
                    )
                else:
                    discovery_result.forward_links.append(
                        DiscoveredLink(
                            source_id=src,
                            source_name=get_zone_name(src),
                            target_id=dst,
                            target_name=get_zone_name(dst),
                            link_type=link_type,
                        )
                    )

                logger.debug(
                    "[DISCOVERY] New link: %s → %s (id=%s, type=%s, category=%s)",
                    src,
                    dst,
                    resolved_zone_link_id,
                    link_type,
                    "main" if is_main_link else "forward",
                )
            else:
                logger.warning("[DISCOVERY] No zone_link_id found for %s → %s", src, dst)

        # If target was not previously discovered, propagate through preexisting
        if dst not in discovered_nodes:
            discovered_nodes.add(dst)
            logger.debug("[DISCOVERY] New node discovered: %s", dst)

            # Propagate through ALL preexisting links from dst
            # (recursive discovery of zones connected via vanilla links)
            # Skip propagation if the link blocks it (e.g., conditional fog gates
            # where the player can't access the rest of the destination zone)
            if blocks_prop:
                logger.debug(
                    "[DISCOVERY] Skipping forward propagation from %s (blocks_propagation)", dst
                )
            else:
                for next_dst, _is_bidir in preexisting_adj.get(dst, []):
                    # Queue for recursive discovery - will be skipped if already visited
                    # These are forward-propagated links (not main)
                    queue.append((dst, next_dst, None, False, False))
                    logger.debug("[DISCOVERY] Queuing preexisting: %s → %s", dst, next_dst)
        else:
            # Both nodes already discovered - check for preexisting links between them
            # that haven't been discovered yet (parallel links scenario)
            all_links = find_all_zone_link_ids(src, dst)
            for link_uuid, link_type in all_links:
                if link_type == "preexisting":
                    # Check if this specific link is already discovered
                    already_discovered = any(
                        get_zone_link_id(dl) == link_uuid for dl in discovered_links
                    )
                    if not already_discovered:
                        new_link = {
                            "zone_link_id": link_uuid,
                            "discovered_at": now,
                            "discovered_by": discovered_by,
                        }
                        discovered_links.append(new_link)
                        discovery_result.forward_links.append(
                            DiscoveredLink(
                                source_id=src,
                                source_name=get_zone_name(src),
                                target_id=dst,
                                target_name=get_zone_name(dst),
                                link_type=link_type,
                            )
                        )
                        logger.debug(
                            "[DISCOVERY] Parallel preexisting link: %s ↔ %s (id=%s)",
                            src,
                            dst,
                            link_uuid,
                        )

    # Update game with new discovered_zone_links
    if discovery_result.total_count() > 0:
        # Log all zone_link_ids being saved
        zone_link_ids_to_save = [dl.get("zone_link_id") for dl in discovered_links]
        logger.debug(
            "[DISCOVERY] Saving %d links, last 5 zone_link_ids: %s",
            len(zone_link_ids_to_save),
            zone_link_ids_to_save[-5:],
        )

        game.discovered_zone_links = discovered_links
        flag_modified(game, "discovered_zone_links")
        await db.flush()

        # Verify the assignment
        logger.debug(
            "[DISCOVERY] After flush, game.discovered_zone_links has %d items",
            len(game.discovered_zone_links) if game.discovered_zone_links else 0,
        )
    else:
        logger.debug("[DISCOVERY] No new links discovered (already known or invalid)")

    return discovery_result
