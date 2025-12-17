"""
Game logic: discovery propagation through preexisting links.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.database import Game
from fogvizu.zone_matching import (
    build_preexisting_adjacency,
    find_candidate_zones,
    find_path_prioritizing_discovered,
    find_similar_zones,
    find_zone_pair,
    get_discovered_nodes,
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


async def propagate_discovery(
    db: AsyncSession,
    game_id: UUID,
    source: str,
    target: str,
    discovered_by: str = "mod",
) -> list[dict[str, str]]:
    """
    Propagate a discovery through preexisting links.
    Returns all newly discovered links (including the initial one).

    Logic:
    1. Record the initial link as discovered
    2. If target was not previously discovered, find all preexisting links
       from target to already-discovered nodes and record them
    3. Recursively propagate through newly reachable preexisting links
    """
    logger.info("[DISCOVERY] Request: '%s' → '%s' (by %s)", source, target, discovered_by)

    # Get game data
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if not game:
        logger.warning("[DISCOVERY] Game %s not found", game_id)
        return []

    zone_pairs = game.zone_pairs
    if not zone_pairs:
        logger.warning("[DISCOVERY] Game %s has no zone_pairs", game_id)
        return []

    # Check if the link exists in zone_pairs
    found_pair = find_zone_pair(zone_pairs, source, target)
    if found_pair:
        logger.info(
            "[DISCOVERY] Found matching pair: %s → %s (type=%s)",
            found_pair["source"],
            found_pair["destination"],
            found_pair["type"],
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
                [(c["source"], c["destination"]) for c in source_candidates[:5]],
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
                [(c["source"], c["destination"]) for c in target_candidates[:5]],
            )
        else:
            similar_target = find_similar_zones(zone_pairs, target)
            if similar_target:
                logger.debug("[DISCOVERY] Similar zones to target '%s': %s", target, similar_target)
            else:
                logger.debug("[DISCOVERY] Target '%s' not found in any zone pair", target)

    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    # Get current discovered links (make a mutable copy)
    discovered_links: list[dict] = list(game.discovered_links) if game.discovered_links else []

    # Get current discovered nodes
    discovered_nodes = get_discovered_nodes(discovered_links)
    logger.debug("[DISCOVERY] Currently %d discovered nodes", len(discovered_nodes))

    # Track newly discovered links
    newly_discovered: list[dict[str, str]] = []
    now = datetime.now(UTC).isoformat()

    # Back-propagation: if source is not accessible from START, find path and discover it
    if not is_accessible_from_start(discovered_links, source):
        logger.info("[DISCOVERY] Source '%s' not accessible from START, back-propagating", source)
        path_to_source = find_path_prioritizing_discovered(zone_pairs, discovered_links, source)
        if path_to_source:
            logger.debug("[DISCOVERY] Back-propagation path: %s", path_to_source)
            for src, dst in path_to_source:
                if not link_exists(discovered_links, src, dst):
                    new_link = {
                        "source": src,
                        "target": dst,
                        "discovered_at": now,
                        "discovered_by": f"{discovered_by} (backprop)",
                    }
                    discovered_links.append(new_link)
                    newly_discovered.append({"source": src, "target": dst})
                    logger.debug("[DISCOVERY] Back-propagated link: %s → %s", src, dst)
            # Update discovered nodes after back-propagation
            discovered_nodes = get_discovered_nodes(discovered_links)
        else:
            logger.warning("[DISCOVERY] No path found from START to '%s'", source)

    # BFS through preexisting links
    queue: list[tuple[str, str]] = [(source, target)]
    visited: set[tuple[str, str]] = set()

    while queue:
        src, dst = queue.pop(0)
        link_key = (src, dst)

        if link_key in visited:
            continue
        visited.add(link_key)

        # Record this link as discovered (if not already)
        if not link_exists(discovered_links, src, dst):
            new_link = {
                "source": src,
                "target": dst,
                "discovered_at": now,
                "discovered_by": discovered_by,
            }
            discovered_links.append(new_link)
            newly_discovered.append({"source": src, "target": dst})
            logger.debug("[DISCOVERY] New link: %s → %s", src, dst)

        # If target was not previously discovered, propagate through preexisting
        if dst not in discovered_nodes:
            discovered_nodes.add(dst)
            logger.debug("[DISCOVERY] New node discovered: %s", dst)

            # Find preexisting links from dst to already-discovered nodes
            for next_dst, _is_bidir in preexisting_adj.get(dst, []):
                if next_dst in discovered_nodes:
                    # Preexisting link to already-discovered node
                    queue.append((dst, next_dst))
                    logger.debug("[DISCOVERY] Queuing preexisting: %s → %s", dst, next_dst)

    # Update game with new discovered_links
    if newly_discovered:
        game.discovered_links = discovered_links
        await db.flush()
        logger.info(
            "[DISCOVERY] Propagated %d new links (total discovered: %d)",
            len(newly_discovered),
            len(discovered_links),
        )
    else:
        logger.info("[DISCOVERY] No new links discovered (already known or invalid)")

    return newly_discovered
