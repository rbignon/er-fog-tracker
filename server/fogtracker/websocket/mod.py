"""
Mod WebSocket client handler.
"""

import contextlib
import logging
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from fogtracker.database import Game, async_session
from fogtracker.game_logic import (
    DiscoveryResult,
    find_all_matching_zone_pairs,
    format_discovery_summary,
    format_ingame_display,
    propagate_discovery,
)
from fogtracker.websocket.auth import authenticate_ws, verify_game_access
from fogtracker.websocket.base import Client
from fogtracker.websocket.manager import manager
from fogtracker.zone_matching import (
    compute_backprop_cost,
    compute_discovery_stats,
    compute_zone_exits,
    expand_discovered_links,
    find_all_matching_zone_pairs_by_keys,
    get_discovered_nodes,
)
from fogtracker.zone_resolver import get_resolver

logger = logging.getLogger(__name__)

# Maximum number of zone candidates to use for matching.
# Lower = more precise (fewer multi-link discoveries), but might miss matches
# if position is slightly off. Higher = more fallback options but more spoilers.
MAX_ZONE_CANDIDATES = 15


class ModClient(Client):
    """Client for the game mod."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
            "discovery_v2": self._handle_discovery_v2,
            "zone_query": self._handle_zone_query,
            "debug_log": self._handle_debug_log,
            "tag_update": self._handle_tag_update,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""

    async def _handle_debug_log(self, data: dict):
        """Handle debug log from mod."""
        message = data.get("message", "")
        logger.info("[MOD DEBUG] %s", message)

    async def _handle_tag_update(self, data: dict):
        """Handle tag update from mod."""
        zone = data.get("zone")
        tags = data.get("tags", [])

        logger.info("[MOD] Tag update for zone %s: %s", zone, tags)

        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()
            if game:
                current_tags = dict(game.tags or {})
                if tags:
                    current_tags[zone] = tags
                else:
                    current_tags.pop(zone, None)
                game.tags = current_tags
                flag_modified(game, "tags")
                await db.commit()

        await manager.broadcast_to_all(self.game_id, data, exclude=self.ws)

    async def _handle_zone_query(self, data: dict):
        """Handle zone query (after fast travel) - returns current zone and exits.

        Uses discovered zones to filter candidates: if a player can fast travel
        to a grace site, the zone must be discovered. This helps disambiguate
        when multiple zones match the same position.
        """
        map_id = data.get("map_id", "")
        pos = data.get("pos", {})
        play_region_id = data.get("play_region_id")

        logger.info(
            "[MOD] Zone query: %s (%.1f, %.1f, %.1f) region=%s",
            map_id,
            pos.get("x", 0),
            pos.get("y", 0),
            pos.get("z", 0),
            play_region_id,
        )

        if not map_id:
            await self.send({"type": "zone_query_ack", "zone": None, "exits": []})
            return

        # Get game data first to know which zones are discovered
        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            if not game:
                await self.send({"type": "zone_query_ack", "zone": None, "exits": []})
                return

            discovered_zones = get_discovered_nodes(
                game.discovered_zone_links or [], game.zone_links or []
            )

            resolver = get_resolver()

            # Try Col resolution first if available
            zone_internal = None
            zone_display = None
            if play_region_id:
                col = f"h{play_region_id:06x}"
                zone_internal, zone_display = resolver.resolve_by_col(map_id, col)
                if zone_display:
                    # Check if Col-resolved zone is discovered
                    if zone_display in discovered_zones:
                        logger.debug("[MOD] Zone resolved by Col (discovered): %s", zone_display)
                    else:
                        logger.debug(
                            "[MOD] Zone resolved by Col but not discovered: %s, trying position",
                            zone_display,
                        )
                        zone_internal, zone_display = None, None

            # Fallback to position-based resolution
            # Only return if exactly 1 discovered candidate (avoid ambiguity)
            if not zone_internal:
                candidates = resolver.resolve_all_candidates(
                    map_id, pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
                )
                if candidates:
                    discovered_candidates = [c for c in candidates if c[1] in discovered_zones]
                    if len(discovered_candidates) == 1:
                        # Exactly one discovered candidate - safe to return
                        zone_internal, zone_display = discovered_candidates[0]
                        logger.debug(
                            "[MOD] Zone resolved by position (1 discovered): %s", zone_display
                        )
                    elif len(discovered_candidates) > 1:
                        # Multiple discovered candidates - ambiguous, return null
                        logger.info(
                            "[MOD] Zone query ambiguous: %d discovered candidates for %s:",
                            len(discovered_candidates),
                            map_id,
                        )
                        for candidate in discovered_candidates:
                            logger.info("[MOD]   - %s", candidate[1])
                    else:
                        # No discovered candidates - return null
                        logger.debug("[MOD] Zone query: no discovered candidates for %s", map_id)

            if not zone_display:
                logger.warning("[MOD] Zone query: no zone found for %s", map_id)
                await self.send({"type": "zone_query_ack", "zone": None, "exits": []})
                return

            # Get exits for the resolved zone
            exits = compute_zone_exits(
                game.zone_links or [],
                game.discovered_zone_links or [],
                zone_display,
            )

            # Compute discovery stats
            stats = compute_discovery_stats(game.zone_links or [], game.discovered_zone_links or [])

        # Log in-game display preview
        ingame = format_ingame_display(zone_display, exits, stats)
        for line in ingame.split("\n"):
            logger.info(line)
        await self.send(
            {
                "type": "zone_query_ack",
                "zone": zone_display,
                "exits": exits,
            }
        )

    async def _handle_discovery_v2(self, data: dict):
        """Handle discovery with map_id + position (server resolves zone names)."""
        logger.debug("[Discover] Received: %s", data)
        source_map_id = data.get("source_map_id")
        source_pos = data.get("source_pos", {})
        source_play_region_id = data.get("source_play_region_id")
        target_map_id = data.get("target_map_id")
        target_pos = data.get("target_pos", {})
        target_play_region_id = data.get("target_play_region_id")
        warp_type = data.get("warp_type", "unknown")
        # FogMod spawn point entity ID (755890xxx) - enables precise matching
        destination_entity_id = data.get("destination_entity_id", 0)

        # Convert play_region_id to Col format (hXXYYZZ)
        source_col = f"h{source_play_region_id:06x}" if source_play_region_id else None
        target_col = f"h{target_play_region_id:06x}" if target_play_region_id else None

        logger.info(
            "[MOD] Discovery v2 [%s]: %s (%.1f, %.1f, %.1f) col=%s -> %s (%.1f, %.1f, %.1f) col=%s dest_entity=%d",
            warp_type,
            source_map_id,
            source_pos.get("x", 0),
            source_pos.get("y", 0),
            source_pos.get("z", 0),
            source_col,
            target_map_id,
            target_pos.get("x", 0),
            target_pos.get("y", 0),
            target_pos.get("z", 0),
            target_col,
            destination_entity_id,
        )

        if not source_map_id or not target_map_id:
            logger.warning("[MOD] Missing map_id in discovery_v2")
            await self.send({"type": "error", "message": "Missing source_map_id or target_map_id"})
            return

        resolver = get_resolver()

        # Try exact Col resolution first (if available)
        source_col_internal, source_col_display = None, None
        target_col_internal, target_col_display = None, None

        if source_col:
            source_col_internal, source_col_display = resolver.resolve_by_col(
                source_map_id, source_col
            )
            if source_col_display:
                logger.info("[MOD] Source resolved by Col: %s", source_col_display)

        if target_col:
            target_col_internal, target_col_display = resolver.resolve_by_col(
                target_map_id, target_col
            )
            if target_col_display:
                logger.info("[MOD] Target resolved by Col: %s", target_col_display)

        # Get all candidate zones for source and target (fallback)
        source_candidates = resolver.resolve_all_candidates(
            source_map_id,
            source_pos.get("x", 0),
            source_pos.get("y", 0),
            source_pos.get("z", 0),
        )
        target_candidates = resolver.resolve_all_candidates(
            target_map_id,
            target_pos.get("x", 0),
            target_pos.get("y", 0),
            target_pos.get("z", 0),
        )

        # If Col resolved, prepend to candidates with highest priority
        if source_col_internal:
            source_candidates = [(source_col_internal, source_col_display)] + [
                c for c in source_candidates if c[0] != source_col_internal
            ]
        if target_col_internal:
            target_candidates = [(target_col_internal, target_col_display)] + [
                c for c in target_candidates if c[0] != target_col_internal
            ]

        logger.debug(
            "[MOD] Zone candidates: source=%s, target=%s",
            [c[1] for c in source_candidates[:5]],
            [c[1] for c in target_candidates[:5]],
        )

        if not source_candidates or not target_candidates:
            logger.warning("[MOD] No zone candidates for %s -> %s", source_map_id, target_map_id)
            await self.send(
                {
                    "type": "discovery_v2_ack",
                    "propagated": [],
                    "resolved": [],
                    "error": "No zone candidates found",
                }
            )
            return

        # Process with fresh DB session (with row lock to prevent race conditions)
        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id).with_for_update())
            game = result.scalar_one_or_none()

            # Collect all discovery results to merge them for the summary
            all_discovery_results: list[DiscoveryResult] = []
            resolved_links = []

            if game and game.zone_links:
                # If entity_mapping is available, use it to improve zone candidate ordering
                if destination_entity_id and game.entity_mapping:
                    entity_info = game.entity_mapping.get(str(destination_entity_id))
                    if entity_info:
                        emevd_source_map = entity_info.get("source_map")
                        emevd_dest_map = entity_info.get("dest_map")
                        logger.info(
                            "[MOD] Entity mapping found for %d: source=%s, dest=%s",
                            destination_entity_id,
                            emevd_source_map,
                            emevd_dest_map,
                        )

                        # Add and prioritize candidates from EMEVD maps
                        # The mod reports the player's tile, but the fog gate may be in a
                        # different tile. EMEVD maps tell us where the fog gate actually is.
                        if emevd_source_map:
                            emevd_source_zones = resolver.resolve_from_map_id(emevd_source_map)
                            if emevd_source_zones:
                                emevd_keys = {z[0] for z in emevd_source_zones}
                                # Add zones from EMEVD map that aren't already in candidates
                                existing_keys = {c[0] for c in source_candidates}
                                new_zones = [
                                    z for z in emevd_source_zones if z[0] not in existing_keys
                                ]
                                # Prioritize: existing matching EMEVD first, then new zones, then rest
                                prioritized_existing = [
                                    c for c in source_candidates if c[0] in emevd_keys
                                ]
                                non_prioritized = [
                                    c for c in source_candidates if c[0] not in emevd_keys
                                ]
                                source_candidates = (
                                    prioritized_existing + new_zones + non_prioritized
                                )
                                if new_zones:
                                    logger.debug(
                                        "[MOD] Added source candidates from entity_mapping: %s",
                                        [c[1] for c in new_zones[:3]],
                                    )
                                elif prioritized_existing:
                                    logger.debug(
                                        "[MOD] Prioritized source candidates from entity_mapping: %s",
                                        [c[1] for c in prioritized_existing[:3]],
                                    )

                        if emevd_dest_map:
                            emevd_dest_zones = resolver.resolve_from_map_id(emevd_dest_map)
                            if emevd_dest_zones:
                                emevd_keys = {z[0] for z in emevd_dest_zones}
                                # Add zones from EMEVD map that aren't already in candidates
                                existing_keys = {c[0] for c in target_candidates}
                                new_zones = [
                                    z for z in emevd_dest_zones if z[0] not in existing_keys
                                ]
                                # Prioritize: existing matching EMEVD first, then new zones, then rest
                                prioritized_existing = [
                                    c for c in target_candidates if c[0] in emevd_keys
                                ]
                                non_prioritized = [
                                    c for c in target_candidates if c[0] not in emevd_keys
                                ]
                                target_candidates = (
                                    prioritized_existing + new_zones + non_prioritized
                                )
                                if new_zones:
                                    logger.debug(
                                        "[MOD] Added target candidates from entity_mapping: %s",
                                        [c[1] for c in new_zones[:3]],
                                    )
                                elif prioritized_existing:
                                    logger.debug(
                                        "[MOD] Prioritized target candidates from entity_mapping: %s",
                                        [c[1] for c in prioritized_existing[:3]],
                                    )

                # Check if zone_links have zone_keys (V3 enrichment)
                has_zone_keys = any(
                    zl.get("source_key") or zl.get("target_key")
                    for zl in game.zone_links[:5]  # Check first few
                )

                if has_zone_keys:
                    # Use key-based matching (more precise)
                    # Find ALL matches, then pick those with lowest back-propagation cost
                    all_matches = find_all_matching_zone_pairs_by_keys(
                        game.zone_links,
                        source_candidates[:MAX_ZONE_CANDIDATES],
                        target_candidates[:MAX_ZONE_CANDIDATES],
                    )
                    if all_matches:
                        logger.info("[MOD] Found %d candidate match(es) by keys", len(all_matches))

                        # Calculate back-propagation cost for each match
                        # Cost = number of random links needed to reach source from START
                        matches_with_cost = []
                        for source_display, target_display, pair in all_matches:
                            cost = compute_backprop_cost(
                                game.zone_links,
                                game.discovered_zone_links or [],
                                source_display,
                            )
                            matches_with_cost.append((source_display, target_display, pair, cost))
                            logger.debug(
                                "[MOD] Match '%s' -> '%s': backprop cost = %d",
                                source_display,
                                target_display,
                                cost,
                            )

                        # Sort by cost (ascending), -1 (unreachable) goes last
                        matches_with_cost.sort(key=lambda x: (x[3] == -1, x[3]))

                        # Get minimum cost (excluding unreachable)
                        reachable = [m for m in matches_with_cost if m[3] >= 0]
                        if reachable:
                            min_cost = reachable[0][3]
                            # Select all matches with minimum cost
                            best_matches = [m for m in reachable if m[3] == min_cost]

                            if len(best_matches) > 1:
                                logger.info(
                                    "[MOD] %d matches tied with cost %d, discovering all",
                                    len(best_matches),
                                    min_cost,
                                )

                            for source_display, target_display, _, cost in best_matches:
                                logger.debug(
                                    "[MOD] Discovered (by keys, cost=%d): '%s' -> '%s'",
                                    cost,
                                    source_display,
                                    target_display,
                                )
                                resolved_links.append(
                                    {"source": source_display, "target": target_display}
                                )
                                discovery_result = await propagate_discovery(
                                    db,
                                    self.game_id,
                                    source_display,
                                    target_display,
                                    discovered_by="mod",
                                )
                                all_discovery_results.append(discovery_result)
                        else:
                            logger.warning(
                                "[MOD] All %d matches are unreachable from START",
                                len(all_matches),
                            )
                    else:
                        logger.debug(
                            "[MOD] No key-based match, falling back to display name matching",
                        )
                        # Fall through to display name matching below
                        has_zone_keys = False

                if not has_zone_keys:
                    # Fallback: use display name matching (legacy behavior)
                    # Also apply backprop cost tie-breaking
                    all_matches = find_all_matching_zone_pairs(
                        game.zone_links,
                        source_candidates[:MAX_ZONE_CANDIDATES],
                        target_candidates[:MAX_ZONE_CANDIDATES],
                    )

                    if all_matches:
                        logger.info(
                            "[MOD] Found %d candidate match(es) by display name", len(all_matches)
                        )

                        # Calculate back-propagation cost for each match
                        matches_with_cost = []
                        for source_display, target_display, pair in all_matches:
                            cost = compute_backprop_cost(
                                game.zone_links,
                                game.discovered_zone_links or [],
                                source_display,
                            )
                            matches_with_cost.append((source_display, target_display, pair, cost))
                            logger.debug(
                                "[MOD] Match '%s' -> '%s': backprop cost = %d",
                                source_display,
                                target_display,
                                cost,
                            )

                        # Sort by cost (ascending), -1 (unreachable) goes last
                        matches_with_cost.sort(key=lambda x: (x[3] == -1, x[3]))

                        # Get minimum cost (excluding unreachable)
                        reachable = [m for m in matches_with_cost if m[3] >= 0]
                        if reachable:
                            min_cost = reachable[0][3]
                            best_matches = [m for m in reachable if m[3] == min_cost]

                            if len(best_matches) > 1:
                                logger.info(
                                    "[MOD] %d matches tied with cost %d, discovering all",
                                    len(best_matches),
                                    min_cost,
                                )

                            for source_display, target_display, _, cost in best_matches:
                                logger.debug(
                                    "[MOD] Discovered (by display name, cost=%d): '%s' -> '%s'",
                                    cost,
                                    source_display,
                                    target_display,
                                )
                                resolved_links.append(
                                    {"source": source_display, "target": target_display}
                                )

                                discovery_result = await propagate_discovery(
                                    db,
                                    self.game_id,
                                    source_display,
                                    target_display,
                                    discovered_by="mod",
                                )
                                all_discovery_results.append(discovery_result)
                        else:
                            logger.warning(
                                "[MOD] All %d matches are unreachable from START",
                                len(all_matches),
                            )
                    else:
                        logger.warning(
                            "[MOD] No spoiler log match (tried %d x %d combinations)",
                            len(source_candidates[:MAX_ZONE_CANDIDATES]),
                            len(target_candidates[:MAX_ZONE_CANDIDATES]),
                        )
            else:
                logger.warning("[MOD] Game has no zone_links, cannot resolve")

            await db.commit()

            # Merge all discovery results into one for summary logging
            # Find the result that actually discovered new links (has main_links)
            # to use its origin for the merged result
            primary_result = None
            for dr in all_discovery_results:
                if dr.main_links:
                    primary_result = dr
                    break
            if not primary_result and all_discovery_results:
                primary_result = all_discovery_results[0]

            merged_result = DiscoveryResult(origin=primary_result.origin if primary_result else "")
            for dr in all_discovery_results:
                merged_result.main_links.extend(dr.main_links)
                merged_result.backprop_links.extend(dr.backprop_links)
                merged_result.forward_links.extend(dr.forward_links)

            # Build flat list for backward compatibility
            all_propagated = merged_result.all_links()

            # Expire cached objects to ensure fresh data after propagate_discovery
            db.expire_all()

            # Refetch game to get fresh data after expire_all()
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            # Compute exits from the destination zone
            # Use the link that actually discovered something new (from primary_result)
            exits = []
            destination_zone = None
            if resolved_links and game:
                # Find the link that corresponds to the primary discovery result
                link = None
                if primary_result and primary_result.main_links:
                    # Match resolved_links to the one with the actual discovery
                    main_target = primary_result.main_links[0].target
                    for rl in resolved_links:
                        if rl["target"] == main_target or rl["source"] == main_target:
                            link = rl
                            break
                if not link:
                    link = resolved_links[0]

                target_display_names = {c[1] for c in target_candidates}

                if link["target"] in target_display_names:
                    destination_zone = link["target"]
                elif link["source"] in target_display_names:
                    destination_zone = link["source"]
                else:
                    destination_zone = link["target"]

                exits = compute_zone_exits(
                    game.zone_links or [],
                    game.discovered_zone_links or [],
                    destination_zone,
                )

            # Compute discovery stats
            stats = {"discovered": 0, "total": 0, "percent": 0}
            if game:
                stats = compute_discovery_stats(
                    game.zone_links or [], game.discovered_zone_links or []
                )

            # Log discovery summary
            if merged_result.total_count() > 0:
                summary = format_discovery_summary(
                    merged_result,
                    discovered_by="mod",
                    total_discovered=stats["discovered"],
                    total_links=stats["total"],
                )
                for line in summary.split("\n"):
                    logger.info(line)

            # Log in-game display preview
            if destination_zone:
                ingame = format_ingame_display(destination_zone, exits, stats)
                for line in ingame.split("\n"):
                    logger.info(line)

            # Send ack to mod
            ack_msg = {
                "type": "discovery_v2_ack",
                "propagated": all_propagated,
                "resolved": resolved_links,
                "current_zone": destination_zone,
                "exits": exits,
                "stats": stats,
            }
            if not resolved_links:
                ack_msg["error"] = "No matching link found in spoiler log"

            await self.send(ack_msg)

            # Broadcast to host and viewers
            if all_propagated:
                # Refetch game to ensure we have ALL discovered_zone_links after multiple propagate calls
                result = await db.execute(select(Game).where(Game.id == self.game_id))
                game = result.scalar_one_or_none()

                if game:
                    raw_links = game.discovered_zone_links or []
                    expanded_links = expand_discovered_links(
                        game.discovered_zone_links or [], game.zone_links or []
                    )

                    # Debug: check if expansion dropped any links
                    if len(expanded_links) != len(raw_links):
                        logger.warning(
                            "[MOD] Expansion lost links! Raw: %d, Expanded: %d",
                            len(raw_links),
                            len(expanded_links),
                        )

                    logger.info(
                        "[MOD] Broadcasting %d propagated links, %d total discovered to host/viewers",
                        len(all_propagated),
                        len(expanded_links),
                    )
                    await manager.broadcast_to_all(
                        self.game_id,
                        {
                            "type": "discovery",
                            "propagated": all_propagated,
                            "discovered_zone_links": expanded_links,
                            "stats": stats,
                            "focus_target": destination_zone,
                        },
                        exclude=self.ws,
                    )
                else:
                    logger.warning("[MOD] Game not found for broadcast after propagation")
            else:
                logger.debug("[MOD] No links propagated, skipping broadcast")

    @classmethod
    async def handle_connection(cls, websocket: WebSocket, game_id: UUID):
        """Handle mod WebSocket connection."""
        await websocket.accept()
        logger.info("[MOD] Connection attempt for game %s", game_id)

        # Auth requires a DB session
        async with async_session() as db:
            # Don't send auth_ok yet - we'll include stats after loading the game
            user = await authenticate_ws(websocket, db, send_auth_ok=False)
            if not user:
                logger.warning("[MOD] Authentication failed for game %s", game_id)
                await websocket.close()
                return

            logger.info("[MOD] Authenticated as user %s (id=%s)", user.twitch_username, user.id)

            game = await verify_game_access(db, game_id, user, require_owner=True)
            if not game:
                logger.warning("[MOD] Game %s not found or not owned by user", game_id)
                await websocket.send_json({"type": "error", "message": "Game not found"})
                await websocket.close()
                return

            logger.info("[MOD] Game access verified: %s (seed=%s)", game.label, game.seed)

            # Compute stats and send auth_ok with stats
            stats = compute_discovery_stats(game.zone_links or [], game.discovered_zone_links or [])
            await websocket.send_json(
                {
                    "type": "auth_ok",
                    "stats": {"discovered": stats["discovered"], "total": stats["total"]},
                }
            )

        # Register in room
        room = manager.get_or_create_room(game_id)
        if room.mod:
            logger.warning("[MOD] Mod already connected for game %s", game_id)
            await websocket.send_json({"type": "error", "message": "Mod already connected"})
            await websocket.close()
            return

        client = cls(websocket, game_id, user)
        room.mod = client
        logger.info("[MOD#%d@%s] Connected to game %s", client._conn_id, client._remote, game_id)

        # Notify host
        if room.host:
            with contextlib.suppress(Exception):
                await room.host.send({"type": "mod_connected"})

        try:
            await client.run()
        finally:
            logger.info(
                "[MOD#%d@%s] Disconnected from game %s", client._conn_id, client._remote, game_id
            )
            # Only clear room.mod if we're still the current mod
            if room.mod is client:
                room.mod = None
                if room.host:
                    with contextlib.suppress(Exception):
                        await room.host.send({"type": "mod_disconnected"})
            manager.cleanup_room(game_id)
