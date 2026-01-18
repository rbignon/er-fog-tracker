"""
Mod WebSocket client handler.
"""

import contextlib
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from fogtracker.config import get_settings
from fogtracker.database import Game, async_session
from fogtracker.game_logic import (
    DiscoveryResult,
    format_discovery_summary,
    format_ingame_display,
    format_resolution_failure,
    format_zone_resolution,
    propagate_discovery,
)
from fogtracker.websocket.auth import authenticate_ws, update_last_seen, verify_game_access
from fogtracker.websocket.base import Client
from fogtracker.websocket.manager import manager
from fogtracker.zone_matching import (
    compute_backprop_cost,
    compute_discovery_stats,
    compute_zone_exits,
    expand_discovered_links,
    find_all_matching_zone_pairs_by_ids,
    get_discovered_nodes,
    get_zone_scaling,
)
from fogtracker.zone_resolver import get_resolver

logger = logging.getLogger(__name__)

# Maximum number of zone candidates to use for matching.
# Lower = more precise (fewer multi-link discoveries), but might miss matches
# if position is slightly off. Higher = more fallback options but more spoilers.
MAX_ZONE_CANDIDATES = 15

# Warp types that are inherently one-way (used to filter ambiguous matches)
ONE_WAY_WARP_TYPES = {
    "PlacidusaxLieDown",  # Lying down in front of the tempest
    "SendingGate",  # Sending gates
    "Coffin",  # Stone coffins
    "Abduction",  # Getting abducted by Abductor Virgins
}

# Mapping of warp_type to source_details pattern for disambiguation
# When multiple matches remain after is_one_way filtering, use these patterns
WARP_TYPE_DETAILS_PATTERNS: dict[str, str] = {
    "PlacidusaxLieDown": "lying down",
    "SendingGate": "sending gate",
    "Coffin": "coffin",
    "Abduction": "abducted",
}


class ModClient(Client):
    """Client for the game mod."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
            "discovery_v2": self._handle_discovery_v2,
            "zone_query": self._handle_zone_query,
            "debug_log": self._handle_debug_log,
            "tag_update": self._handle_tag_update,
            "upload_logs": self._handle_upload_logs,
            "game_stats_update": self._handle_game_stats_update,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""

    async def _handle_debug_log(self, data: dict):
        """Handle debug log from mod."""
        message = data.get("message", "")
        logger.info("[MOD DEBUG] %s", message)

    async def _handle_upload_logs(self, data: dict):
        """Handle log upload from mod.

        Saves the log content to: {reports_dir}/{game_id}/{YYmmdd_HHMM}/mod.log
        """
        content = data.get("content", "")

        reports_dir = get_settings().reports_dir
        if not reports_dir:
            logger.warning("[MOD] Log upload failed: REPORTS_DIR not configured")
            await self.send(
                {
                    "type": "upload_logs_ack",
                    "success": False,
                    "message": "Reports directory not configured on server",
                }
            )
            return

        # Create directory: {reports_dir}/{game_id}/{YYmmdd_HHMM}/
        timestamp_dir = datetime.now().strftime("%y%m%d_%H%M")
        output_dir = Path(reports_dir) / str(self.game_id) / timestamp_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        file_path = output_dir / "mod.log"
        file_path.write_text(content, encoding="utf-8")

        logger.info(
            "[MOD] Logs uploaded: %d bytes -> %s",
            len(content),
            file_path,
        )

        await self.send(
            {
                "type": "upload_logs_ack",
                "success": True,
            }
        )

    # -------------------------------------------------------------------------
    # Helper methods for zone resolution and discovery
    # -------------------------------------------------------------------------

    def _resolve_zone_candidates(
        self, map_id: str, pos: dict, play_region_id: int | None, label: str = ""
    ) -> list[tuple[str, str]]:
        """Resolve zone candidates for a map position.

        Uses Col resolution first (most precise), then position-based fallback.
        Returns list of (zone_key, display_name) tuples, with Col result first if found.
        """
        resolver = get_resolver()

        # Try Col resolution first
        col_internal, col_display = None, None
        if play_region_id:
            col = f"h{play_region_id:06x}"
            col_internal, col_display = resolver.resolve_by_col(map_id, col)
            if col_display:
                logger.info("[MOD] %s resolved by Col: %s", label or "Zone", col_display)

        # Get position-based candidates
        candidates = resolver.resolve_all_candidates(
            map_id,
            pos.get("x", 0),
            pos.get("y", 0),
            pos.get("z", 0),
        )

        # Prepend Col result if found
        if col_internal:
            candidates = [(col_internal, col_display)] + [
                c for c in candidates if c[0] != col_internal
            ]

        return candidates

    def _merge_discovery_results(
        self, all_discovery_results: list[DiscoveryResult]
    ) -> tuple[DiscoveryResult, DiscoveryResult | None]:
        """Merge multiple discovery results into one.

        Returns (merged_result, primary_result) where primary_result is the one
        that actually discovered new links (has main_links).
        """
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

        return merged_result, primary_result

    async def _finalize_and_send_discovery(
        self,
        db,
        resolved_links: list[dict],
        all_discovery_results: list[DiscoveryResult],
        target_candidates: list[tuple[str, str]],
        error_msg_if_empty: str,
        warp_type: str | None = None,
        resolution_method: str | None = None,
        source_candidates: list[tuple[str, str]] | None = None,
        source_map_id: str | None = None,
        target_map_id: str | None = None,
    ):
        """Finalize discovery: compute stats, log, send ack, and broadcast.

        This method handles the common post-discovery flow:
        1. Merge discovery results
        2. Refetch game data
        3. Compute destination zone and exits
        4. Compute stats
        5. Log summary
        6. Send ack to mod
        7. Broadcast to host/viewers
        """
        merged_result, primary_result = self._merge_discovery_results(all_discovery_results)
        all_propagated = merged_result.all_links()
        propagated_for_mod = [
            {"source": link["source_name"], "target": link["target_name"]}
            for link in all_propagated
        ]

        # Expire and refetch game
        db.expire_all()
        result = await db.execute(select(Game).where(Game.id == self.game_id))
        game = result.scalar_one_or_none()

        # Compute destination zone and exits
        exits = []
        destination_zone = None
        destination_zone_id = None
        if resolved_links and game:
            # Find the link that corresponds to the primary discovery result
            link = None
            if primary_result and primary_result.main_links:
                main_target = primary_result.main_links[0].target_name
                for rl in resolved_links:
                    if rl["target"] == main_target or rl["source"] == main_target:
                        link = rl
                        break
            if not link:
                # No new links discovered (re-traversing already-discovered links)
                # Prefer 'random' type links over 'preexisting' since the player just
                # traversed a randomized fog gate, not a vanilla connection
                zone_links = game.zone_links or []
                resolver = get_resolver()

                # Build lookup: (source_id, target_id) -> link type
                # Only store the canonical direction from zone_links. We also store
                # the reverse direction only for bidirectional links (not is_one_way).
                link_type_lookup: dict[tuple[str, str], str] = {}
                for zl in zone_links:
                    src_id = zl.get("source_id")
                    tgt_id = zl.get("target_id")
                    if src_id and tgt_id:
                        link_type = zl.get("type", "random")
                        link_type_lookup[(src_id, tgt_id)] = link_type
                        # Only add reverse direction for bidirectional links
                        if not zl.get("is_one_way", False):
                            link_type_lookup[(tgt_id, src_id)] = link_type

                # Try to find a random link first
                for rl in resolved_links:
                    src_id = resolver.lookup_by_display_name(rl["source"])
                    tgt_id = resolver.lookup_by_display_name(rl["target"])
                    if src_id and tgt_id:
                        link_type = link_type_lookup.get((src_id, tgt_id))
                        if link_type == "random":
                            link = rl
                            logger.debug(
                                "[MOD] Selected random link for destination: %s -> %s",
                                rl["source"],
                                rl["target"],
                            )
                            break

                # Fall back to first resolved link if no random link found
                if not link:
                    link = resolved_links[0]

            target_display_names = {c[1] for c in target_candidates}
            target_zone_ids = {c[0] for c in target_candidates}

            if link["target"] in target_display_names:
                destination_zone = link["target"]
            elif link["source"] in target_display_names:
                destination_zone = link["source"]
            else:
                destination_zone = link["target"]

            # Resolve zone_id for compute_zone_exits (expects zone_id, not display name)
            resolver = get_resolver()
            destination_zone_id = resolver.lookup_by_display_name(destination_zone)

            # Prefer zone_id from target_candidates if available (more precise)
            if destination_zone_id not in target_zone_ids and target_zone_ids:
                # Fallback: use the first matching zone_id from candidates
                for zid, zname in target_candidates:
                    if zname == destination_zone:
                        destination_zone_id = zid
                        break

            if destination_zone_id:
                exits = compute_zone_exits(
                    game.zone_links or [],
                    game.discovered_zone_links or [],
                    destination_zone_id,
                )

        # Compute stats
        stats = {"discovered": 0, "total": 0, "percent": 0}
        if game:
            stats = compute_discovery_stats(
                game.zone_links or [], game.discovered_zone_links or [], game.zones
            )

        # Log discovery summary
        if merged_result.total_count() > 0:
            summary = format_discovery_summary(
                merged_result,
                discovered_by="mod",
                total_discovered=stats["discovered"],
                total_links=stats["total"],
                warp_type=warp_type,
                resolution_method=resolution_method,
            )
            for line in summary.split("\n"):
                logger.info(line)

        # Log in-game display preview or resolution failure
        if destination_zone:
            ingame = format_ingame_display(destination_zone, exits, stats)
            for line in ingame.split("\n"):
                logger.info(line)
        elif not resolved_links:
            # Build map_id string for failure log
            if source_map_id and target_map_id:
                map_id_str = f"{source_map_id} -> {target_map_id}"
            elif target_map_id:
                map_id_str = f"-> {target_map_id}"
            else:
                map_id_str = "unknown"

            # Build candidates list for failure log
            candidates = []
            if source_candidates:
                candidates.extend([c[1] for c in source_candidates[:3]])
                candidates.append("->")
            if target_candidates:
                candidates.extend([c[1] for c in target_candidates[:3]])

            failure = format_resolution_failure(
                context="discovery_v2",
                map_id=map_id_str,
                reason=error_msg_if_empty,
                candidates=candidates if candidates else None,
            )
            for line in failure.split("\n"):
                logger.warning(line)

        # Get zone scaling (destination_zone_id already computed above if resolved_links)
        scaling = None
        if destination_zone_id and game:
            scaling = get_zone_scaling(game.zones, destination_zone_id)

        # Send ack to mod
        ack_msg = {
            "type": "discovery_v2_ack",
            "propagated": propagated_for_mod,
            "resolved": resolved_links,
            "current_zone": destination_zone,
            "current_zone_id": destination_zone_id,
            "exits": exits,
            "stats": stats,
            "scaling": scaling,
        }
        if not resolved_links:
            ack_msg["error"] = error_msg_if_empty

        await self.send(ack_msg)

        # Broadcast to host and viewers
        if all_propagated:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            if game:
                raw_links = game.discovered_zone_links or []
                expanded_links = expand_discovered_links(
                    game.discovered_zone_links or [], game.zone_links or []
                )

                if len(expanded_links) != len(raw_links):
                    logger.warning(
                        "[MOD] Expansion lost links! Raw: %d, Expanded: %d",
                        len(raw_links),
                        len(expanded_links),
                    )

                logger.info(
                    "[MOD] Broadcasting %d propagated links, %d total discovered",
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
                        "focus_target_id": destination_zone_id,
                    },
                    exclude=self.ws,
                )
            else:
                logger.warning("[MOD] Game not found for broadcast after propagation")
        else:
            logger.debug("[MOD] No links propagated, skipping broadcast")

    # -------------------------------------------------------------------------
    # Message handlers
    # -------------------------------------------------------------------------

    async def _handle_tag_update(self, data: dict):
        """Handle tag update from mod."""
        zone_id = data.get("zone_id")
        tags = data.get("tags", [])

        if not zone_id:
            logger.warning("[MOD] Tag update missing zone_id")
            return

        # Validate tags to prevent JSON bloat attacks
        if not isinstance(tags, list):
            logger.warning("[MOD] Tag update rejected: tags must be a list")
            return
        if len(tags) > 50:
            logger.warning("[MOD] Tag update rejected: too many tags (%d > 50)", len(tags))
            return
        for tag in tags:
            if not isinstance(tag, str) or len(tag) > 100:
                logger.warning(
                    "[MOD] Tag update rejected: invalid tag (must be string <= 100 chars)"
                )
                return

        logger.info("[MOD] Tag update for zone %s: %s", zone_id, tags)

        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()
            if game:
                current_tags = dict(game.tags or {})
                if tags:
                    current_tags[zone_id] = tags
                else:
                    current_tags.pop(zone_id, None)
                game.tags = current_tags
                flag_modified(game, "tags")
                await db.commit()

        await manager.broadcast_to_all(self.game_id, data, exclude=self.ws)

    async def _handle_game_stats_update(self, data: dict):
        """Handle game stats update from mod.

        Updates the game_stats JSONB column and broadcasts to host/viewers.
        Stats include: great_runes (list), kindling_count, death_count, play_time_ms.
        """
        great_runes = data.get("great_runes", [])
        kindling_count = data.get("kindling_count", 0)
        death_count = data.get("death_count", 0)
        play_time_ms = data.get("play_time_ms", 0)

        # Validate great_runes
        if not isinstance(great_runes, list):
            logger.warning("[MOD] game_stats_update: great_runes must be a list")
            return
        if len(great_runes) > 7:  # Max 7 great runes in the game
            logger.warning(
                "[MOD] game_stats_update rejected: too many great_runes (%d > 7)", len(great_runes)
            )
            return

        # Validate rune names (must be known runes)
        valid_runes = {"Godrick", "Radahn", "Morgott", "Rykard", "Mohg", "Malenia", "Unborn"}
        for rune in great_runes:
            if not isinstance(rune, str) or rune not in valid_runes:
                logger.warning("[MOD] game_stats_update rejected: unknown rune '%s'", rune)
                return

        # Validate numeric fields
        if not isinstance(kindling_count, int) or kindling_count < 0:
            logger.warning("[MOD] game_stats_update: invalid kindling_count")
            return
        if not isinstance(death_count, int) or death_count < 0:
            logger.warning("[MOD] game_stats_update: invalid death_count")
            return
        if not isinstance(play_time_ms, int) or play_time_ms < 0:
            logger.warning("[MOD] game_stats_update: invalid play_time_ms")
            return

        logger.info(
            "[MOD] Game stats update: runes=%s, kindling=%d, deaths=%d, igt=%dms",
            great_runes,
            kindling_count,
            death_count,
            play_time_ms,
        )

        # Update database
        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            if game:
                game.game_stats = {
                    "great_runes": great_runes,
                    "kindling_count": kindling_count,
                    "death_count": death_count,
                    "play_time_ms": play_time_ms,
                }
                flag_modified(game, "game_stats")
                await db.commit()

        # Send acknowledgment to mod
        await self.send({"type": "game_stats_update_ack"})

        # Broadcast to host and viewers
        await manager.broadcast_to_all(
            self.game_id,
            {
                "type": "game_stats_update",
                "great_runes": great_runes,
                "kindling_count": kindling_count,
                "death_count": death_count,
                "play_time_ms": play_time_ms,
            },
            exclude=self.ws,
        )

    async def _handle_zone_query(self, data: dict):
        """Handle zone query (after fast travel) - returns current zone and exits.

        Resolution priority:
        1. Grace entity ID (most precise for fast travel)
        2. Col/play_region_id resolution
        3. Position-based resolution with discovered zone filtering
        """
        map_id = data.get("map_id", "")
        pos = data.get("pos", {})
        play_region_id = data.get("play_region_id")
        grace_entity_id = data.get("grace_entity_id")

        logger.info(
            "[MOD] >>> ZONE QUERY <<< %s (%.1f, %.1f, %.1f) grace=%s",
            map_id,
            pos.get("x", 0),
            pos.get("y", 0),
            pos.get("z", 0),
            grace_entity_id,
        )

        if not map_id:
            await self.send({"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []})
            return

        # Get game data first to know which zones are discovered
        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            if not game:
                await self.send(
                    {"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []}
                )
                return

            starting_zone_id = game.starting_zone_id or "chapel_start"
            discovered_zones = get_discovered_nodes(
                game.discovered_zone_links or [], game.zone_links or [], starting_zone_id
            )

            zone_internal = None
            zone_display = None

            resolution_method = None

            # 1. Try grace entity ID resolution (most precise for fast travel)
            resolver = get_resolver()
            if grace_entity_id:
                grace_info = resolver.get_grace_info(grace_entity_id)
                if grace_info:
                    # Use zone_id directly from graces.json (avoids display name ambiguity)
                    grace_zone_id = grace_info.get("zone_id")
                    grace_zone = grace_info.get("zone")
                    if grace_zone_id and grace_zone_id in discovered_zones:
                        zone_internal = grace_zone_id
                        zone_display = grace_zone
                        resolution_method = "Grace entity ID"
                    else:
                        logger.debug(
                            "[MOD] Grace zone '%s' (id=%s) not discovered, falling back",
                            grace_zone,
                            grace_zone_id,
                        )

            # 2. Try Col resolution if grace didn't work
            if not zone_display and play_region_id:
                col = f"h{play_region_id:06x}"
                zone_internal, zone_display = resolver.resolve_by_col(map_id, col)
                if zone_display:
                    # Check if Col-resolved zone is discovered (zone_internal is the zone_id)
                    if zone_internal in discovered_zones:
                        resolution_method = "Col/play_region_id"
                    else:
                        logger.debug(
                            "[MOD] Zone resolved by Col but not discovered: %s, trying position",
                            zone_display,
                        )
                        zone_internal, zone_display = None, None

            # 3. Fallback to position-based resolution
            # Only return if exactly 1 discovered candidate (avoid ambiguity)
            all_candidates = []
            if not zone_display:
                candidates = resolver.resolve_all_candidates(
                    map_id, pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
                )
                all_candidates = [c[1] for c in candidates] if candidates else []
                if candidates:
                    # Check zone_id (c[0]) against discovered_zones (set of zone_ids)
                    discovered_candidates = [c for c in candidates if c[0] in discovered_zones]
                    if len(discovered_candidates) == 1:
                        # Exactly one discovered candidate - safe to return
                        zone_internal, zone_display = discovered_candidates[0]
                        resolution_method = "Position (unique match)"
                    elif len(discovered_candidates) > 1:
                        # Multiple discovered candidates - ambiguous, return null
                        logger.debug(
                            "[MOD] Zone query ambiguous: %d discovered candidates",
                            len(discovered_candidates),
                        )

            if not zone_display:
                # Log failure with visual format
                if all_candidates:
                    reason = f"Ambiguous ({len(all_candidates)} candidates, none unique)"
                else:
                    reason = "No zone candidates found"
                failure = format_resolution_failure(
                    context="zone_query",
                    map_id=map_id,
                    reason=reason,
                    candidates=all_candidates[:5] if all_candidates else None,
                )
                for line in failure.split("\n"):
                    logger.warning(line)
                await self.send(
                    {"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []}
                )
                return

            # Get exits for the resolved zone (use zone_id, not display name)
            exits = compute_zone_exits(
                game.zone_links or [],
                game.discovered_zone_links or [],
                zone_internal,
            )

            # Compute discovery stats
            stats = compute_discovery_stats(
                game.zone_links or [], game.discovered_zone_links or [], game.zones
            )

        # Log zone resolution summary
        resolution = format_zone_resolution(
            zone=zone_display,
            method=resolution_method or "Unknown",
            exits_count=len(exits),
            stats=stats,
            grace_entity_id=grace_entity_id if resolution_method == "Grace entity ID" else None,
        )
        for line in resolution.split("\n"):
            logger.info(line)

        # Log in-game display preview
        ingame = format_ingame_display(zone_display, exits, stats)
        for line in ingame.split("\n"):
            logger.info(line)

        # Get zone_id and scaling
        zone_id = resolver.lookup_by_display_name(zone_display) if zone_display else None
        scaling = get_zone_scaling(game.zones, zone_id) if zone_id else None

        await self.send(
            {
                "type": "zone_query_ack",
                "zone": zone_display,
                "zone_id": zone_id,
                "exits": exits,
                "scaling": scaling,
            }
        )

    async def _handle_medal_discovery(self, data: dict):
        """Handle Medal warp discovery.

        The Pureblood Knight's Medal can be used from anywhere, so we cannot use
        the source position to find the link. Instead, we find the link with
        required_item="Pureblood Knight's Medal" and match only by destination.
        """
        target_map_id = data.get("target_map_id")
        target_pos = data.get("target_pos", {})
        target_play_region_id = data.get("target_play_region_id")

        logger.info(
            "[MOD] Medal discovery: target=%s (%.1f, %.1f, %.1f)",
            target_map_id,
            target_pos.get("x", 0),
            target_pos.get("y", 0),
            target_pos.get("z", 0),
        )

        # Resolve target candidates
        target_candidates = self._resolve_zone_candidates(
            target_map_id, target_pos, target_play_region_id, label="Target"
        )

        if not target_candidates:
            logger.warning("[MOD] No target zone candidates for Medal warp to %s", target_map_id)
            await self.send(
                {
                    "type": "discovery_v2_ack",
                    "propagated": [],
                    "resolved": [],
                    "error": "No target zone candidates found for Medal warp",
                }
            )
            return

        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id).with_for_update())
            game = result.scalar_one_or_none()

            resolved_links = []
            all_discovery_results: list[DiscoveryResult] = []

            if game and game.zone_links:
                # Find the Medal link (required_item = "Pureblood Knight's Medal")
                medal_link = next(
                    (
                        zl
                        for zl in game.zone_links
                        if zl.get("required_item") == "Pureblood Knight's Medal"
                    ),
                    None,
                )

                if not medal_link:
                    logger.warning("[MOD] No Medal link found in zone_links")
                    await self.send(
                        {
                            "type": "discovery_v2_ack",
                            "propagated": [],
                            "resolved": [],
                            "error": "No Medal link found in spoiler log",
                        }
                    )
                    return

                # Check if any target candidate matches the medal link's target
                target_display_names = {c[1] for c in target_candidates[:MAX_ZONE_CANDIDATES]}
                target_ids = {c[0] for c in target_candidates[:MAX_ZONE_CANDIDATES]}

                medal_target = medal_link.get("target")
                medal_target_id = medal_link["target_id"]

                match_found = False
                resolution_method = None
                if medal_target_id and medal_target_id in target_ids:
                    match_found = True
                    resolution_method = "zone_ids"
                    logger.info("[MOD] Medal target matched by zone_id: %s", medal_target)
                elif medal_target in target_display_names:
                    match_found = True
                    resolution_method = "display_name"
                    logger.info("[MOD] Medal target matched by display name: %s", medal_target)

                if match_found:
                    source_display = medal_link["source"]
                    source_id = medal_link["source_id"]
                    resolved_links.append({"source": source_display, "target": medal_target})

                    discovery_result = await propagate_discovery(
                        db,
                        self.game_id,
                        source_id,
                        medal_target_id,
                        discovered_by="mod",
                    )
                    all_discovery_results.append(discovery_result)
                else:
                    logger.warning(
                        "[MOD] Medal target '%s' (id=%s) not in candidates: %s",
                        medal_target,
                        medal_target_id,
                        [c[1] for c in target_candidates[:5]],
                    )

            await db.commit()

            await self._finalize_and_send_discovery(
                db,
                resolved_links,
                all_discovery_results,
                target_candidates,
                error_msg_if_empty="Medal target not found in candidates",
                warp_type="Medal",
                resolution_method=resolution_method,
                target_map_id=target_map_id,
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
        # Source zone from mod's cached state (optional, for disambiguation)
        source_zone = data.get("source_zone")
        source_zone_id = data.get("source_zone_id")

        # Convert play_region_id to Col format (hXXYYZZ)
        source_col = f"h{source_play_region_id:06x}" if source_play_region_id else None
        target_col = f"h{target_play_region_id:06x}" if target_play_region_id else None

        logger.info(
            "[MOD] >>> DISCOVERY <<< [%s] %s -> %s (entity=%d)",
            warp_type,
            source_map_id,
            target_map_id,
            destination_entity_id,
        )
        logger.debug(
            "[MOD] Discovery details: source=(%.1f, %.1f, %.1f) col=%s zone=%s | target=(%.1f, %.1f, %.1f) col=%s",
            source_pos.get("x", 0),
            source_pos.get("y", 0),
            source_pos.get("z", 0),
            source_col,
            source_zone,
            target_pos.get("x", 0),
            target_pos.get("y", 0),
            target_pos.get("z", 0),
            target_col,
        )

        if not source_map_id or not target_map_id:
            logger.warning("[MOD] Missing map_id in discovery_v2")
            await self.send({"type": "error", "message": "Missing source_map_id or target_map_id"})
            return

        # Handle Medal warp specially: the medal can be used from anywhere,
        # so we ignore the source position and find the link by required_item
        if warp_type == "Medal":
            await self._handle_medal_discovery(data)
            return

        # Resolve zone candidates for source and target
        source_candidates = self._resolve_zone_candidates(
            source_map_id, source_pos, source_play_region_id, label="Source"
        )
        target_candidates = self._resolve_zone_candidates(
            target_map_id, target_pos, target_play_region_id, label="Target"
        )

        # If source_zone provided by mod, use it to improve candidate selection
        # This prevents discovering multiple links when only one fog gate was traversed
        # The mod has direct game state access and knows which zone the player was in
        mod_source_authoritative = False
        if source_zone or source_zone_id:
            prioritized = []
            for candidate in source_candidates:
                zone_key, zone_display = candidate
                if (source_zone_id and zone_key == source_zone_id) or (
                    source_zone and zone_display == source_zone
                ):
                    prioritized.append(candidate)
            if prioritized:
                source_candidates = prioritized
                mod_source_authoritative = True
                logger.info(
                    "[MOD] Filtered source zone from mod: %s (id=%s)",
                    prioritized[0][1],
                    prioritized[0][0],
                )
            elif source_zone_id:
                # Mod's source_zone_id not in candidates - this can happen when:
                # - Player is at a fog gate entrance in an overworld zone (e.g., Caelid)
                # - But the fog gate is physically in a dungeon map (e.g., m31_21_00_00)
                # - The dungeon map only has dungeon zones as candidates
                # Trust the mod's zone info and add it as a candidate
                resolver = get_resolver()
                display_name = resolver.zone_display_names.get(source_zone_id)
                if display_name:
                    source_candidates = [(source_zone_id, display_name)] + source_candidates
                    logger.info(
                        "[MOD] Injected mod's source zone as candidate: %s (id=%s)",
                        display_name,
                        source_zone_id,
                    )

        # Filter candidates based on animation requirements
        # Zones that require a specific animation (e.g., Medal for Pureblood Knight's Medal)
        # are only valid candidates when that animation is used
        resolver = get_resolver()
        source_candidates = resolver.filter_candidates_by_animation(
            source_candidates, source_map_id, warp_type
        )
        target_candidates = resolver.filter_candidates_by_animation(
            target_candidates, target_map_id, warp_type
        )

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
            resolution_method = None

            if game and game.zone_links:
                # Get starting_zone_id for graph traversal functions
                starting_zone_id = game.starting_zone_id or "chapel_start"

                # If entity_mapping is available, use it to improve zone candidate ordering
                # We compute expanded candidates separately so we can use them as fallback
                expanded_source_candidates = source_candidates
                if destination_entity_id and game.entity_mapping:
                    resolver = get_resolver()
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
                                expanded_source_candidates = (
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

                # Find ALL matches using zone_id-based matching, then pick lowest backprop cost
                # Use mod's filtered source if authoritative, otherwise use expanded candidates
                source_for_matching = (
                    source_candidates if mod_source_authoritative else expanded_source_candidates
                )
                all_matches = find_all_matching_zone_pairs_by_ids(
                    game.zone_links,
                    source_for_matching[:MAX_ZONE_CANDIDATES],
                    target_candidates[:MAX_ZONE_CANDIDATES],
                )

                # Fallback: if mod provided authoritative source but no matches found,
                # retry with entity_mapping expanded candidates
                if not all_matches and mod_source_authoritative:
                    logger.warning(
                        "[MOD] No match with mod's source_zone_id=%s, "
                        "falling back to entity_mapping expansion",
                        source_zone_id,
                    )
                    all_matches = find_all_matching_zone_pairs_by_ids(
                        game.zone_links,
                        expanded_source_candidates[:MAX_ZONE_CANDIDATES],
                        target_candidates[:MAX_ZONE_CANDIDATES],
                    )
                    if all_matches:
                        # Update source_for_matching for later use in lookup tables
                        source_for_matching = expanded_source_candidates
                        logger.info(
                            "[MOD] Fallback succeeded: found %d match(es)", len(all_matches)
                        )

                if all_matches:
                    logger.info("[MOD] Found %d candidate match(es)", len(all_matches))

                    # Disambiguation: filter matches based on warp_type
                    if len(all_matches) > 1:
                        # Option 2: Filter by is_one_way for known one-way warp types
                        if warp_type in ONE_WAY_WARP_TYPES:
                            one_way_matches = [
                                m for m in all_matches if m[2].get("is_one_way", False)
                            ]
                            if one_way_matches:
                                logger.debug(
                                    "[MOD] Filtered to %d one-way match(es) for warp_type=%s",
                                    len(one_way_matches),
                                    warp_type,
                                )
                                all_matches = one_way_matches

                        # Option 1: Filter by source_details pattern if still ambiguous
                        if len(all_matches) > 1 and warp_type in WARP_TYPE_DETAILS_PATTERNS:
                            pattern = WARP_TYPE_DETAILS_PATTERNS[warp_type].lower()
                            pattern_matches = [
                                m
                                for m in all_matches
                                if pattern in (m[2].get("source_details") or "").lower()
                            ]
                            if pattern_matches:
                                logger.debug(
                                    "[MOD] Filtered to %d match(es) by source_details pattern '%s'",
                                    len(pattern_matches),
                                    pattern,
                                )
                                all_matches = pattern_matches

                    # Build lookup tables to convert zone_ids back to display names
                    # find_all_matching_zone_pairs_by_ids returns (source_id, target_id, pair)
                    source_id_to_name = {
                        zid: name for zid, name in source_for_matching[:MAX_ZONE_CANDIDATES]
                    }
                    target_id_to_name = {
                        zid: name for zid, name in target_candidates[:MAX_ZONE_CANDIDATES]
                    }

                    # Calculate back-propagation cost for each match
                    # Cost = number of random links needed to reach source from START
                    matches_with_cost = []
                    for source_id, target_id, pair in all_matches:
                        # Look up display names from candidates
                        source_display = source_id_to_name.get(
                            source_id, pair.get("source", source_id)
                        )
                        target_display = target_id_to_name.get(
                            target_id, pair.get("target", target_id)
                        )
                        cost = compute_backprop_cost(
                            game.zone_links,
                            game.discovered_zone_links or [],
                            pair["source_id"],
                            starting_zone_id,
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

                        resolution_method = "zone_keys"
                        for source_display, target_display, pair, cost in best_matches:
                            logger.debug(
                                "[MOD] Discovered (cost=%d): '%s' -> '%s'",
                                cost,
                                source_display,
                                target_display,
                            )
                            resolved_links.append(
                                {"source": source_display, "target": target_display}
                            )
                            # Use zone_ids from the pair for propagate_discovery
                            discovery_result = await propagate_discovery(
                                db,
                                self.game_id,
                                pair["source_id"],
                                pair["target_id"],
                                discovered_by="mod",
                            )
                            all_discovery_results.append(discovery_result)
                    else:
                        logger.warning(
                            "[MOD] All %d matches are unreachable from START",
                            len(all_matches),
                        )
            else:
                logger.warning("[MOD] Game has no zone_links, cannot resolve")

            await db.commit()

            await self._finalize_and_send_discovery(
                db,
                resolved_links,
                all_discovery_results,
                target_candidates,
                error_msg_if_empty="No matching link found in spoiler log",
                warp_type=warp_type,
                resolution_method=resolution_method,
                source_candidates=source_candidates,
                source_map_id=source_map_id,
                target_map_id=target_map_id,
            )

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
            stats = compute_discovery_stats(
                game.zone_links or [], game.discovered_zone_links or [], game.zones
            )
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
        await update_last_seen(user.id)
        logger.info("[MOD#%d@%s] Connected to game %s", client._conn_id, client._remote, game_id)

        # Notify host and viewers
        if room.host:
            with contextlib.suppress(Exception):
                await room.host.send({"type": "mod_connected"})
        await manager.broadcast_to_viewers(game_id, {"type": "mod_connected"})

        try:
            await client.run()
        finally:
            logger.info(
                "[MOD#%d@%s] Disconnected from game %s", client._conn_id, client._remote, game_id
            )
            if client.user:
                await update_last_seen(client.user.id)
            # Only clear room.mod if we're still the current mod
            if room.mod is client:
                room.mod = None
                if room.host:
                    with contextlib.suppress(Exception):
                        await room.host.send({"type": "mod_disconnected"})
                await manager.broadcast_to_viewers(game_id, {"type": "mod_disconnected"})
            manager.cleanup_room(game_id)
