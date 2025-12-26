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

from fogvizu.database import Game
from fogvizu.zone_matching import (
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
from fogvizu.zone_matching import (  # noqa: E402, F401
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

    source: str
    target: str
    link_type: str  # "random" or "preexisting"


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
        """Return all links as a flat list (for backward compatibility)."""
        result = []
        for link in self.backprop_links + self.main_links + self.forward_links:
            result.append({"source": link.source, "target": link.target})
        return result

    def total_count(self) -> int:
        """Return total number of newly discovered links."""
        return len(self.backprop_links) + len(self.main_links) + len(self.forward_links)


def format_discovery_summary(
    result: DiscoveryResult,
    discovered_by: str,
    total_discovered: int | None = None,
    total_links: int | None = None,
) -> str:
    """Format a discovery result as a visual summary for logging."""
    lines = []

    # Header
    lines.append("╭─ Discovery Summary ─────────────────────────────────────────")
    lines.append(f"│ Origin:     {result.origin}")

    # Main discovered link(s)
    if result.main_links:
        for link in result.main_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│ Link:       {link.source} {arrow} {link.target}")

    # Back-propagation section
    if result.backprop_links:
        lines.append(f"├─ Back-propagation ({len(result.backprop_links)}):")
        for link in result.backprop_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│   ◂ {link.source} {arrow} {link.target}")

    # Forward-propagation section
    if result.forward_links:
        lines.append(f"├─ Forward-propagation ({len(result.forward_links)}):")
        for link in result.forward_links:
            arrow = "───>" if link.link_type == "random" else "--->"
            lines.append(f"│   ▸ {link.source} {arrow} {link.target}")

    # Footer with stats
    total = result.total_count()
    link_word = "link" if total == 1 else "links"
    footer = f"╰─ Total: {total} new {link_word}"
    if total_discovered is not None and total_links is not None:
        percent = (total_discovered / total_links * 100) if total_links > 0 else 0
        footer += f" │ Progress: {total_discovered}/{total_links} ({percent:.1f}%)"
    lines.append(footer)

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
    source: str,
    target: str,
    discovered_by: str = "mod",
    link_id: str | None = None,
) -> DiscoveryResult:
    """
    Propagate a discovery through preexisting links.
    Returns a DiscoveryResult with categorized newly discovered links.

    Logic:
    1. Record the initial link as discovered
    2. If target was not previously discovered, find all preexisting links
       from target to already-discovered nodes and record them
    3. Recursively propagate through newly reachable preexisting links
    """
    logger.debug("[DISCOVERY] Request: '%s' → '%s' (by %s)", source, target, discovered_by)

    # Initialize result with origin
    discovery_result = DiscoveryResult(origin=source)

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

    # Build index to look up link type by source/target
    def get_link_type(src: str, dst: str) -> str:
        """Get the type of a link (random or preexisting)."""
        for zp in zone_pairs:
            if (zp["source"] == src and zp["target"] == dst) or (
                zp["source"] == dst and zp["target"] == src
            ):
                return zp.get("type", "random")
        return "random"

    # Check if the link exists in zone_links
    found_pair = find_zone_pair(zone_pairs, source, target)
    main_link_type = "random"
    if found_pair:
        # Use exact names from zone_links for consistency
        source = found_pair["source"]
        target = found_pair["target"]
        main_link_type = found_pair.get("type", "random")
        discovery_result.origin = source  # Update origin with exact name
        logger.debug(
            "[DISCOVERY] Found matching pair: %s → %s (type=%s)",
            source,
            target,
            main_link_type,
        )
    else:
        logger.warning("[DISCOVERY] No matching pair found for '%s' → '%s'", source, target)

        # Log candidates for source zone
        source_candidates = find_candidate_zones(zone_pairs, source)
        if source_candidates:
            logger.debug(
                "[DISCOVERY] Source '%s' found in %d pairs: %s",
                source,
                len(source_candidates),
                [(c["source"], c["target"]) for c in source_candidates[:5]],
            )
        else:
            similar_source = find_similar_zones(zone_pairs, source)
            if similar_source:
                logger.debug("[DISCOVERY] Similar zones to source '%s': %s", source, similar_source)
            else:
                logger.debug("[DISCOVERY] Source '%s' not found in any zone pair", source)

        # Log candidates for target zone
        target_candidates = find_candidate_zones(zone_pairs, target)
        if target_candidates:
            logger.debug(
                "[DISCOVERY] Target '%s' found in %d pairs: %s",
                target,
                len(target_candidates),
                [(c["source"], c["target"]) for c in target_candidates[:5]],
            )
        else:
            similar_target = find_similar_zones(zone_pairs, target)
            if similar_target:
                logger.debug("[DISCOVERY] Similar zones to target '%s': %s", target, similar_target)
            else:
                logger.debug("[DISCOVERY] Target '%s' not found in any zone pair", target)

    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    # Build index for finding zone_link_id by source/target
    zp_by_endpoints: dict[tuple[str, str], str] = {}
    for zp in zone_pairs:
        zp_id = zp.get("id")
        if zp_id:
            zp_by_endpoints[(zp["source"], zp["target"])] = zp_id

    def find_zone_link_id(src: str, dst: str) -> str | None:
        """Find zone_link ID for a source/target pair."""
        return zp_by_endpoints.get((src, dst)) or zp_by_endpoints.get((dst, src))

    # Get current discovered links (make a mutable copy)
    discovered_links: list[dict] = (
        list(game.discovered_zone_links) if game.discovered_zone_links else []
    )

    # Get current discovered nodes
    discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs)
    logger.debug("[DISCOVERY] Currently %d discovered nodes", len(discovered_nodes))

    now = datetime.now(UTC).isoformat()

    # Track zones newly discovered via back-propagation (need to propagate their preexisting)
    backprop_new_zones: set[str] = set()

    # Back-propagation: if source is not accessible from START, find path and discover it
    if not is_accessible_from_start(discovered_links, source, zone_pairs):
        logger.debug("[DISCOVERY] Source '%s' not accessible from START, back-propagating", source)
        path_to_source = find_path_prioritizing_discovered(zone_pairs, discovered_links, source)
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
                            DiscoveredLink(source=src, target=dst, link_type=link_type)
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
            discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs)

            # Collect zones newly discovered via back-propagation
            # These zones need their preexisting links propagated
            for _src, dst in path_to_source:
                backprop_new_zones.add(dst)
            # The source itself is also newly accessible
            backprop_new_zones.add(source)
            logger.debug("[DISCOVERY] Zones newly accessible via backprop: %s", backprop_new_zones)
        else:
            logger.warning("[DISCOVERY] No path found from START to '%s'", source)

    # Build index for looking up ALL links between two zones (not just one direction)
    def find_all_zone_link_ids(src: str, dst: str) -> list[tuple[str, str]]:
        """Find all zone_link IDs for links between src and dst (both directions)."""
        results = []
        for zp in zone_pairs:
            zp_id = zp.get("id")
            if not zp_id:
                continue
            zp_src = zp["source"]
            zp_dst = zp["target"]
            # Match either direction
            if (zp_src == src and zp_dst == dst) or (zp_src == dst and zp_dst == src):
                results.append((zp_id, zp["type"]))
        return results

    # BFS through preexisting links
    # For the initial link, use provided link_id if available
    # Mark the initial link specially so we can identify it
    queue: list[tuple[str, str, str | None, bool]] = [(source, target, link_id, True)]
    visited: set[tuple[str, str]] = set()

    # Also queue preexisting links from zones newly discovered via back-propagation
    # These zones are now accessible but their preexisting links haven't been propagated
    for zone in backprop_new_zones:
        for next_dst, _is_bidir in preexisting_adj.get(zone, []):
            queue.append((zone, next_dst, None, False))
            logger.debug(
                "[DISCOVERY] Queuing preexisting from backprop zone: %s → %s", zone, next_dst
            )

    while queue:
        src, dst, provided_link_id, is_main_link = queue.pop(0)
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
                        DiscoveredLink(source=src, target=dst, link_type=link_type)
                    )
                else:
                    discovery_result.forward_links.append(
                        DiscoveredLink(source=src, target=dst, link_type=link_type)
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
            for next_dst, _is_bidir in preexisting_adj.get(dst, []):
                # Queue for recursive discovery - will be skipped if already visited
                # These are forward-propagated links (not main)
                queue.append((dst, next_dst, None, False))
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
                            DiscoveredLink(source=src, target=dst, link_type=link_type)
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
