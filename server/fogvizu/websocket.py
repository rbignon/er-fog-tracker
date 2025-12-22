"""
WebSocket connection manager and client handlers.
"""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import or_, select
from sqlalchemy.orm.attributes import flag_modified

from fogvizu.config import settings
from fogvizu.database import Game, User, async_session
from fogvizu.game_logic import find_all_matching_zone_pairs, propagate_discovery
from fogvizu.zone_matching import (
    compute_backprop_cost,
    compute_discovery_stats,
    compute_zone_exits,
    expand_discovered_links,
    find_all_matching_zone_pairs_by_keys,
)
from fogvizu.zone_resolver import get_resolver

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# =============================================================================
# Client Base Class
# =============================================================================


class Client(ABC):
    """Base class for WebSocket clients."""

    _next_id = 0

    def __init__(self, ws: WebSocket, game_id: UUID, user: User | None = None):
        self.ws = ws
        self.game_id = game_id
        self.user = user
        self._handlers: dict[str, callable] = {}
        self._running = False
        # Unique connection ID for debugging
        Client._next_id += 1
        self._conn_id = Client._next_id
        # Extract remote address for logging
        client = ws.client
        self._remote = f"{client.host}:{client.port}" if client else "unknown"

    @abstractmethod
    def _register_handlers(self) -> dict[str, callable]:
        """Return message type -> handler mapping."""
        pass

    async def send(self, message: dict):
        """Send a message to the client."""
        await self.ws.send_json(message)

    async def run(self):
        """Main loop - handle heartbeat and message dispatch."""
        self._handlers = self._register_handlers()
        self._running = True

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._message_loop())

    async def _heartbeat_loop(self):
        """Send periodic pings to keep connection alive."""
        interval = settings.heartbeat_interval
        while self._running:
            try:
                await self.ws.send_json({"type": "ping"})
            except Exception as e:
                logger.warning(
                    "[%s#%d@%s] Heartbeat failed: %s",
                    self.__class__.__name__,
                    self._conn_id,
                    self._remote,
                    e,
                )
                self._running = False
                break

            await asyncio.sleep(interval)

    async def _message_loop(self):
        """Receive and dispatch messages to handlers."""
        try:
            while self._running:
                data = await self.ws.receive_json()
                msg_type = data.get("type")
                # logger.debug("[%s:%s RX] %s", self.__class__.__name__, str(self.game_id)[:8], data)

                handler = self._handlers.get(msg_type)
                if handler:
                    try:
                        await handler(data)
                    except Exception as e:
                        logger.exception(
                            "[%s] Handler error for %s: %s", self.__class__.__name__, msg_type, e
                        )
                elif msg_type != "pong":
                    logger.warning(
                        "[%s] Unknown message type: %s", self.__class__.__name__, msg_type
                    )
        except WebSocketDisconnect as e:
            logger.info(
                "[%s#%d@%s] WebSocket disconnect: code=%s",
                self.__class__.__name__,
                self._conn_id,
                self._remote,
                e.code,
            )
        except Exception as e:
            logger.warning(
                "[%s#%d@%s] Message loop error: %s (%s)",
                self.__class__.__name__,
                self._conn_id,
                self._remote,
                e,
                type(e).__name__,
            )
        finally:
            logger.debug(
                "[%s#%d@%s] Connection closed", self.__class__.__name__, self._conn_id, self._remote
            )
            self._running = False

    def stop(self):
        """Stop the client."""
        self._running = False


# =============================================================================
# Mod Client
# =============================================================================


class ModClient(Client):
    """Client for the game mod."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
            "discovery_v2": self._handle_discovery_v2,
            "debug_log": self._handle_debug_log,
            "tag_update": self._handle_tag_update,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""
        logger.debug("[MOD] Pong received")

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

        # Process with fresh DB session
        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            all_propagated = []
            resolved_links = []

            if game and game.zone_pairs:
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

                        # Prioritize candidates that match the EMEVD maps
                        if emevd_source_map:
                            # Get zones for this map and prioritize them
                            emevd_source_zones = resolver.resolve_from_map_id(emevd_source_map)
                            if emevd_source_zones:
                                # Move matching candidates to the front
                                emevd_keys = {z[0] for z in emevd_source_zones}
                                prioritized = [c for c in source_candidates if c[0] in emevd_keys]
                                others = [c for c in source_candidates if c[0] not in emevd_keys]
                                if prioritized:
                                    source_candidates = prioritized + others
                                    logger.debug(
                                        "[MOD] Prioritized source candidates from entity_mapping: %s",
                                        [c[1] for c in prioritized[:3]],
                                    )

                        if emevd_dest_map:
                            # Get zones for this map and prioritize them
                            emevd_dest_zones = resolver.resolve_from_map_id(emevd_dest_map)
                            if emevd_dest_zones:
                                # Move matching candidates to the front
                                emevd_keys = {z[0] for z in emevd_dest_zones}
                                prioritized = [c for c in target_candidates if c[0] in emevd_keys]
                                others = [c for c in target_candidates if c[0] not in emevd_keys]
                                if prioritized:
                                    target_candidates = prioritized + others
                                    logger.debug(
                                        "[MOD] Prioritized target candidates from entity_mapping: %s",
                                        [c[1] for c in prioritized[:3]],
                                    )

                # Check if zone_pairs have zone_keys (V3 enrichment)
                has_zone_keys = any(
                    zp.get("source_key") or zp.get("destination_key")
                    for zp in game.zone_pairs[:5]  # Check first few
                )

                if has_zone_keys:
                    # Use key-based matching (more precise)
                    # Find ALL matches, then pick those with lowest back-propagation cost
                    all_matches = find_all_matching_zone_pairs_by_keys(
                        game.zone_pairs,
                        source_candidates[:15],
                        target_candidates[:15],
                    )
                    if all_matches:
                        logger.info("[MOD] Found %d candidate match(es) by keys", len(all_matches))

                        # Calculate back-propagation cost for each match
                        # Cost = number of random links needed to reach source from START
                        matches_with_cost = []
                        for source_display, target_display, pair in all_matches:
                            cost = compute_backprop_cost(
                                game.zone_pairs,
                                game.discovered_links or [],
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
                                logger.info(
                                    "[MOD] Discovered (by keys, cost=%d): '%s' -> '%s'",
                                    cost,
                                    source_display,
                                    target_display,
                                )
                                resolved_links.append(
                                    {"source": source_display, "target": target_display}
                                )
                                propagated = await propagate_discovery(
                                    db,
                                    self.game_id,
                                    source_display,
                                    target_display,
                                    discovered_by="mod",
                                )
                                all_propagated.extend(propagated)
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
                    matches = find_all_matching_zone_pairs(
                        game.zone_pairs,
                        source_candidates[:15],
                        target_candidates[:15],
                    )

                    if matches:
                        logger.info("[MOD] Found %d valid link(s) in spoiler log", len(matches))
                        for source_display, target_display, _ in matches:
                            logger.info(
                                "[MOD] Discovered: '%s' -> '%s'", source_display, target_display
                            )
                            resolved_links.append(
                                {"source": source_display, "target": target_display}
                            )

                            propagated = await propagate_discovery(
                                db,
                                self.game_id,
                                source_display,
                                target_display,
                                discovered_by="mod",
                            )
                            all_propagated.extend(propagated)
                    else:
                        logger.warning(
                            "[MOD] No spoiler log match (tried %d x %d combinations)",
                            len(source_candidates[:15]),
                            len(target_candidates[:15]),
                        )
            else:
                logger.warning("[MOD] Game has no zone_pairs, cannot resolve")

            await db.commit()

            # Expire cached objects to ensure fresh data after propagate_discovery
            db.expire_all()

            # Refetch game to get fresh data after expire_all()
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

            # Compute exits from the destination zone
            exits = []
            destination_zone = None
            if resolved_links and game:
                link = resolved_links[0]
                target_display_names = {c[1] for c in target_candidates}

                if link["target"] in target_display_names:
                    destination_zone = link["target"]
                elif link["source"] in target_display_names:
                    destination_zone = link["source"]
                else:
                    destination_zone = link["target"]

                logger.info("[MOD] Player arrived at zone: %s", destination_zone)

                exits = compute_zone_exits(
                    game.zone_pairs or [],
                    game.discovered_links or [],
                    destination_zone,
                )
                logger.info("[MOD] Computed %d exits from zone '%s'", len(exits), destination_zone)

            # Compute discovery stats
            stats = {"discovered": 0, "total": 0, "percent": 0}
            if game:
                stats = compute_discovery_stats(game.zone_pairs or [], game.discovered_links or [])

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

            logger.info(
                "[MOD TX] Ack: %d resolved, %d propagated, %d exits, discovered %d/%d (%.1f%%)",
                len(resolved_links),
                len(all_propagated),
                len(exits),
                stats["discovered"],
                stats["total"],
                stats["percent"],
            )
            await self.send(ack_msg)

            # Broadcast to host and viewers
            if all_propagated:
                # Refetch game to ensure we have ALL discovered_links after multiple propagate calls
                result = await db.execute(select(Game).where(Game.id == self.game_id))
                game = result.scalar_one_or_none()

                if game:
                    # Debug: log raw discovered_links before expansion
                    raw_links = game.discovered_links or []
                    logger.debug(
                        "[MOD] Before expand: %d raw links, last 5 link_ids: %s",
                        len(raw_links),
                        [dl.get("link_id") for dl in raw_links[-5:]],
                    )

                    expanded_links = expand_discovered_links(
                        game.discovered_links or [], game.zone_pairs or []
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
                            "discovered_links": expanded_links,
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
            user = await authenticate_ws(websocket, db)
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


# =============================================================================
# Host Client
# =============================================================================


class HostClient(Client):
    """Client for the host (streamer browser)."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
            "visual_state": self._handle_visual_state,
            "positions_update": self._handle_positions_update,
            "tag_update": self._handle_tag_update,
            "manual_discovery": self._handle_manual_discovery,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""
        logger.debug("[HOST] Pong received")

    async def _handle_visual_state(self, data: dict):
        """Handle visual state update from host."""
        room = manager.rooms.get(self.game_id)
        if room:
            room.last_visual_state = data
        await manager.broadcast_to_viewers(self.game_id, data)

    async def _handle_positions_update(self, data: dict):
        """Handle node positions update."""
        positions = data.get("positions", {})

        async with async_session() as db:
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()
            if game:
                current_positions = dict(game.node_positions or {})
                current_positions.update(positions)
                game.node_positions = current_positions
                flag_modified(game, "node_positions")
                await db.commit()

        await manager.broadcast_to_viewers(self.game_id, data)

    async def _handle_tag_update(self, data: dict):
        """Handle tag update for a zone."""
        zone = data.get("zone")
        tags = data.get("tags", [])

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

    async def _handle_manual_discovery(self, data: dict):
        """Handle manual discovery from host."""
        source = data.get("source")
        target = data.get("target")

        if not source or not target:
            return

        async with async_session() as db:
            propagated = await propagate_discovery(
                db, self.game_id, source, target, discovered_by="manual"
            )
            await db.commit()

            # Refetch game to get full discovered_links
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

        if game:
            expanded_links = expand_discovered_links(
                game.discovered_links or [], game.zone_pairs or []
            )
            await manager.broadcast_to_all(
                self.game_id,
                {
                    "type": "discovery",
                    "propagated": propagated,
                    "discovered_links": expanded_links,
                },
                exclude=self.ws,
            )

    @classmethod
    async def handle_connection(cls, websocket: WebSocket, game_id: UUID):
        """Handle host WebSocket connection."""
        await websocket.accept()

        async with async_session() as db:
            user = await authenticate_ws(websocket, db)
            if not user:
                await websocket.close()
                return

            game = await verify_game_access(db, game_id, user, require_owner=True)
            if not game:
                await websocket.send_json({"type": "error", "message": "Game not found"})
                await websocket.close()
                return

            # Send current game state
            zone_pairs = game.zone_pairs or []
            zp_index = {zp["id"]: zp for zp in zone_pairs if zp.get("id")}
            expanded_links = []
            for dl in game.discovered_links or []:
                zp = zp_index.get(dl["link_id"])
                if zp:
                    expanded_links.append({"source": zp["source"], "target": zp["destination"]})

            game_state = {
                "discovered_links": expanded_links,
                "node_positions": game.node_positions or {},
                "tags": game.tags or {},
            }
            await websocket.send_json({"type": "game_state", "state": game_state})

        # Register in room
        room = manager.get_or_create_room(game_id)
        if room.host:
            # Same user reconnecting (e.g., page reload) - take over the session
            if room.host.user and room.host.user.id == user.id:
                logger.info(
                    "[HOST] Same user reconnecting, closing old connection for game %s", game_id
                )
                old_host = room.host
                old_host.stop()
                with contextlib.suppress(Exception):
                    await old_host.ws.close()
                room.host = None
            else:
                await websocket.send_json({"type": "error", "message": "Host already connected"})
                await websocket.close()
                return

        client = cls(websocket, game_id, user)
        room.host = client
        logger.info(
            "[HOST#%d@%s] Connected to game %s (user: %s)",
            client._conn_id,
            client._remote,
            game_id,
            user.twitch_username,
        )

        if room.mod:
            await client.send({"type": "mod_connected"})

        try:
            await client.run()
        except Exception as e:
            logger.exception("[HOST#%d] Error in client.run(): %s", client._conn_id, e)
        finally:
            logger.info(
                "[HOST#%d@%s] Disconnected from game %s", client._conn_id, client._remote, game_id
            )
            # Only clear room.host if we're still the current host (not replaced by a reconnection)
            if room.host is client:
                room.host = None
            manager.cleanup_room(game_id)


# =============================================================================
# Viewer Client
# =============================================================================


class ViewerClient(Client):
    """Client for viewers (read-only, no auth required)."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""
        pass

    @classmethod
    async def handle_connection(cls, websocket: WebSocket, game_id: UUID):
        """Handle viewer WebSocket connection (no auth required)."""
        await websocket.accept()

        async with async_session() as db:
            game = await verify_game_access(db, game_id)
            if not game:
                await websocket.send_json({"type": "error", "message": "Game not found"})
                await websocket.close()
                return

        room = manager.get_or_create_room(game_id)
        if len(room.viewers) >= settings.max_viewers_per_game:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Maximum viewers ({settings.max_viewers_per_game}) reached",
                }
            )
            await websocket.close()
            return

        client = cls(websocket, game_id)
        room.viewers.append(client)
        logger.info(
            "[VIEWER#%d@%s] Connected to game %s (total viewers: %d)",
            client._conn_id,
            client._remote,
            game_id,
            len(room.viewers),
        )

        # Send current state
        if room.last_visual_state:
            await client.send(room.last_visual_state)
        else:
            await client.send({"type": "waiting", "message": "Waiting for host to connect"})

        try:
            await client.run()
        finally:
            logger.info(
                "[VIEWER#%d@%s] Disconnected from game %s", client._conn_id, client._remote, game_id
            )
            if client in room.viewers:
                room.viewers.remove(client)
            manager.cleanup_room(game_id)


# =============================================================================
# Game Room
# =============================================================================


@dataclass
class GameRoom:
    """Tracks all connections for a game."""

    game_id: UUID
    mod: ModClient | None = None
    host: HostClient | None = None
    viewers: list[ViewerClient] = field(default_factory=list)
    last_visual_state: dict | None = None


# =============================================================================
# Connection Manager
# =============================================================================


class ConnectionManager:
    """Manages WebSocket connections for all games."""

    def __init__(self):
        self.rooms: dict[UUID, GameRoom] = {}

    def get_or_create_room(self, game_id: UUID) -> GameRoom:
        """Get or create a room for a game."""
        if game_id not in self.rooms:
            self.rooms[game_id] = GameRoom(game_id=game_id)
        return self.rooms[game_id]

    def cleanup_room(self, game_id: UUID):
        """Remove room if empty."""
        room = self.rooms.get(game_id)
        if room and not room.mod and not room.host and not room.viewers:
            del self.rooms[game_id]

    def is_mod_connected(self, game_id: UUID) -> bool:
        """Check if a mod is connected to a game."""
        room = self.rooms.get(game_id)
        return room is not None and room.mod is not None

    async def broadcast_to_viewers(self, game_id: UUID, message: dict):
        """Broadcast message to all viewers of a game."""
        room = self.rooms.get(game_id)
        if not room:
            logger.debug("[BROADCAST] No room for viewers broadcast, game %s", game_id)
            return

        if not room.viewers:
            logger.debug("[BROADCAST] No viewers in room for game %s", game_id)
            return

        disconnected = []
        sent_count = 0
        for viewer in room.viewers:
            try:
                await viewer.send(message)
                sent_count += 1
            except Exception as e:
                logger.debug("[BROADCAST] Failed to send to viewer: %s", e)
                disconnected.append(viewer)

        for viewer in disconnected:
            room.viewers.remove(viewer)

        logger.debug("[BROADCAST] Sent to %d viewers for game %s", sent_count, game_id)

    async def broadcast_to_all(
        self, game_id: UUID, message: dict, exclude: WebSocket | None = None
    ):
        """Broadcast message to host and all viewers."""
        room = self.rooms.get(game_id)
        if not room:
            logger.warning("[BROADCAST] No room found for game %s", game_id)
            return

        # Send to host
        if room.host and room.host.ws != exclude:
            try:
                await room.host.send(message)
                logger.debug("[BROADCAST] Sent to host for game %s", game_id)
            except Exception as e:
                logger.warning("[BROADCAST] Failed to send to host: %s", e)
                room.host = None
        elif not room.host:
            logger.debug(
                "[BROADCAST] No host connected for game %s (room has: mod=%s, viewers=%d)",
                game_id,
                room.mod is not None,
                len(room.viewers),
            )

        # Send to viewers
        await self.broadcast_to_viewers(game_id, message)


manager = ConnectionManager()


# =============================================================================
# Authentication Helper
# =============================================================================


async def authenticate_ws(websocket: WebSocket, db: "AsyncSession") -> User | None:
    """Wait for auth message and validate token."""
    try:
        logger.debug("[AUTH] Waiting for auth message...")
        data = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        logger.debug("[AUTH] Received: %s", {**data, "token": "***" if data.get("token") else None})

        if data.get("type") != "auth":
            logger.warning("[AUTH] Expected auth message, got: %s", data.get("type"))
            await websocket.send_json({"type": "auth_error", "message": "Expected auth message"})
            return None

        token = data.get("token")
        if not token:
            logger.warning("[AUTH] Missing token")
            await websocket.send_json({"type": "auth_error", "message": "Missing token"})
            return None

        result = await db.execute(
            select(User).where(or_(User.api_token == token, User.mod_token == token))
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("[AUTH] Invalid token")
            await websocket.send_json({"type": "auth_error", "message": "Invalid token"})
            return None

        logger.info("[AUTH] Success for user %s", user.twitch_username)
        await websocket.send_json({"type": "auth_ok"})
        return user

    except TimeoutError:
        logger.warning("[AUTH] Timeout waiting for auth message")
        await websocket.send_json({"type": "auth_error", "message": "Auth timeout"})
        return None
    except Exception as e:
        logger.exception("[AUTH] Error: %s", e)
        return None


async def verify_game_access(
    db: "AsyncSession", game_id: UUID, user: User | None = None, require_owner: bool = False
) -> Game | None:
    """Verify game exists and optionally check ownership."""
    query = select(Game).where(Game.id == game_id).where(Game.deleted_at.is_(None))
    if require_owner and user:
        query = query.where(Game.user_id == user.id)
    result = await db.execute(query)
    return result.scalar_one_or_none()
