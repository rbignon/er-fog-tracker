"""
WebSocket connection manager and handlers.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.config import settings
from fogvizu.database import Game, User, async_session
from fogvizu.game_logic import find_matching_zone_pair, propagate_discovery
from fogvizu.zone_resolver import get_resolver

logger = logging.getLogger(__name__)


@dataclass
class GameRoom:
    """Tracks all connections for a game."""

    game_id: UUID
    mod: WebSocket | None = None
    host: WebSocket | None = None
    viewers: list[WebSocket] = field(default_factory=list)
    last_visual_state: dict | None = None


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

    async def broadcast_to_viewers(self, game_id: UUID, message: dict):
        """Broadcast message to all viewers of a game."""
        room = self.rooms.get(game_id)
        if not room:
            return

        disconnected = []
        for viewer in room.viewers:
            try:
                await viewer.send_json(message)
            except Exception:
                disconnected.append(viewer)

        for viewer in disconnected:
            room.viewers.remove(viewer)

    async def broadcast_to_all(
        self, game_id: UUID, message: dict, exclude: WebSocket | None = None
    ):
        """Broadcast message to host and all viewers."""
        room = self.rooms.get(game_id)
        if not room:
            return

        # Send to host
        if room.host and room.host != exclude:
            try:
                await room.host.send_json(message)
            except Exception:
                room.host = None

        # Send to viewers
        await self.broadcast_to_viewers(game_id, message)


manager = ConnectionManager()


# =============================================================================
# Authentication Helper
# =============================================================================


async def authenticate_ws(websocket: WebSocket, db: AsyncSession) -> User | None:
    """Wait for auth message and validate token.

    Accepts either api_token (from browser) or mod_token (from game mod).
    """
    try:
        # Wait for auth message (5 second timeout)
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

        # Validate token - check both api_token and mod_token
        from sqlalchemy import or_

        result = await db.execute(
            select(User).where(or_(User.api_token == token, User.mod_token == token))
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("[AUTH] Invalid token (not found in database)")
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
        logger.exception("[AUTH] Error during authentication: %s", e)
        return None


async def verify_game_access(
    db: AsyncSession, game_id: UUID, user: User | None = None, require_owner: bool = False
) -> Game | None:
    """Verify game exists and optionally check ownership."""
    query = select(Game).where(Game.id == game_id).where(Game.deleted_at.is_(None))

    if require_owner and user:
        query = query.where(Game.user_id == user.id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


# =============================================================================
# Heartbeat
# =============================================================================


async def heartbeat_loop(websocket: WebSocket, interval: int = None):
    """Send periodic pings to keep connection alive."""
    interval = interval or settings.heartbeat_interval
    while True:
        await asyncio.sleep(interval)
        try:
            await websocket.send_json({"type": "ping"})
        except Exception:
            break


# =============================================================================
# Mod WebSocket Handler
# =============================================================================


async def handle_mod_connection(websocket: WebSocket, game_id: UUID):
    """Handle mod WebSocket connection."""
    await websocket.accept()
    logger.info("[MOD] Connection attempt for game %s", game_id)

    async with async_session() as db:
        # Authenticate
        user = await authenticate_ws(websocket, db)
        if not user:
            logger.warning("[MOD] Authentication failed for game %s", game_id)
            await websocket.close()
            return

        logger.info("[MOD] Authenticated as user %s (id=%s)", user.twitch_username, user.id)

        # Verify game access
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

        room.mod = websocket
        logger.info("[MOD] Connected successfully for game %s", game_id)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                logger.debug("[MOD RX] %s", data)

                if msg_type == "pong":
                    logger.debug("[MOD] Pong received")
                    continue

                elif msg_type == "discovery":
                    # Legacy discovery with zone names from mod
                    source = data.get("source")
                    target = data.get("target")
                    source_map_id = data.get("source_map_id", "?")
                    target_map_id = data.get("target_map_id", "?")
                    logger.info(
                        "[MOD] Discovery (legacy): '%s' [%s] → '%s' [%s]",
                        source,
                        source_map_id,
                        target,
                        target_map_id,
                    )

                    if not source or not target:
                        logger.warning("[MOD] Missing source or target in discovery")
                        await websocket.send_json(
                            {"type": "error", "message": "Missing source or target"}
                        )
                        continue

                    # Propagate discovery
                    propagated = await propagate_discovery(
                        db, game_id, source, target, discovered_by="mod"
                    )
                    await db.commit()

                    # Send ack to mod
                    ack_msg = {"type": "discovery_ack", "propagated": propagated}
                    logger.info("[MOD TX] Ack with %d propagated links", len(propagated))
                    logger.debug("[MOD TX] %s", ack_msg)
                    await websocket.send_json(ack_msg)

                    # Broadcast to host and viewers
                    if propagated:
                        await manager.broadcast_to_all(
                            game_id,
                            {"type": "discovery", "propagated": propagated},
                            exclude=websocket,
                        )

                elif msg_type == "discovery_v2":
                    # New discovery with map_id + position + play_region_id (server resolves zone names)
                    source_map_id = data.get("source_map_id")
                    source_pos = data.get("source_pos", {})
                    source_play_region_id = data.get("source_play_region_id")
                    target_map_id = data.get("target_map_id")
                    target_pos = data.get("target_pos", {})
                    target_play_region_id = data.get("target_play_region_id")

                    # Convert play_region_id to Col format (hXXYYZZ)
                    source_col = f"h{source_play_region_id:06x}" if source_play_region_id else None
                    target_col = f"h{target_play_region_id:06x}" if target_play_region_id else None

                    logger.info(
                        "[MOD] Discovery v2: %s (%.1f, %.1f, %.1f) col=%s → %s (%.1f, %.1f, %.1f) col=%s",
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
                    )

                    if not source_map_id or not target_map_id:
                        logger.warning("[MOD] Missing map_id in discovery_v2")
                        await websocket.send_json(
                            {"type": "error", "message": "Missing source_map_id or target_map_id"}
                        )
                        continue

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
                        [c[1] for c in source_candidates],
                        [c[1] for c in target_candidates],
                    )

                    if not source_candidates or not target_candidates:
                        logger.warning(
                            "[MOD] No zone candidates for %s → %s",
                            source_map_id,
                            target_map_id,
                        )
                        await websocket.send_json(
                            {
                                "type": "discovery_v2_ack",
                                "propagated": [],
                                "resolved_source": None,
                                "resolved_target": None,
                                "error": "No zone candidates found",
                            }
                        )
                        continue

                    # Get game's zone_pairs to find matching combination
                    result = await db.execute(select(Game).where(Game.id == game_id))
                    game_for_zones = result.scalar_one_or_none()

                    source_display = None
                    target_display = None

                    if game_for_zones and game_for_zones.zone_pairs:
                        # Find which combination of candidates matches the spoiler log
                        match = find_matching_zone_pair(
                            game_for_zones.zone_pairs,
                            source_candidates,
                            target_candidates,
                        )
                        if match:
                            source_display, target_display, _ = match
                            logger.info(
                                "[MOD] Matched zones from spoiler log: '%s' → '%s'",
                                source_display,
                                target_display,
                            )
                        else:
                            # No match found - use best guesses for logging
                            source_display = source_candidates[0][1] if source_candidates else None
                            target_display = target_candidates[0][1] if target_candidates else None
                            logger.warning(
                                "[MOD] No spoiler log match for %s → %s (tried %d × %d combinations)",
                                source_display,
                                target_display,
                                len(source_candidates),
                                len(target_candidates),
                            )
                    else:
                        # No zone_pairs - fall back to best guess
                        source_display = source_candidates[0][1] if source_candidates else None
                        target_display = target_candidates[0][1] if target_candidates else None
                        logger.warning("[MOD] Game has no zone_pairs, using best guess")

                    logger.info(
                        "[MOD] Resolved zones: '%s' → '%s'",
                        source_display,
                        target_display,
                    )

                    if not source_display or not target_display:
                        await websocket.send_json(
                            {
                                "type": "discovery_v2_ack",
                                "propagated": [],
                                "resolved_source": source_display,
                                "resolved_target": target_display,
                                "error": "Could not resolve zone names",
                            }
                        )
                        continue

                    # Propagate discovery using display names
                    propagated = await propagate_discovery(
                        db, game_id, source_display, target_display, discovered_by="mod"
                    )
                    await db.commit()

                    # Send ack to mod
                    ack_msg = {
                        "type": "discovery_v2_ack",
                        "propagated": propagated,
                        "resolved_source": source_display,
                        "resolved_target": target_display,
                    }
                    logger.info("[MOD TX] Ack with %d propagated links", len(propagated))
                    logger.debug("[MOD TX] %s", ack_msg)
                    await websocket.send_json(ack_msg)

                    # Broadcast to host and viewers
                    if propagated:
                        await manager.broadcast_to_all(
                            game_id,
                            {"type": "discovery", "propagated": propagated},
                            exclude=websocket,
                        )

                else:
                    logger.warning("[MOD] Unknown message type: %s", msg_type)

        except WebSocketDisconnect:
            logger.info("[MOD] Disconnected for game %s", game_id)
        except Exception as e:
            logger.exception("[MOD] Connection error for game %s: %s", game_id, e)
        finally:
            heartbeat_task.cancel()
            room.mod = None
            manager.cleanup_room(game_id)
            logger.info("[MOD] Cleaned up for game %s", game_id)


# =============================================================================
# Host WebSocket Handler
# =============================================================================


async def handle_host_connection(websocket: WebSocket, game_id: UUID):
    """Handle host (streamer browser) WebSocket connection."""
    await websocket.accept()

    async with async_session() as db:
        # Authenticate
        user = await authenticate_ws(websocket, db)
        if not user:
            await websocket.close()
            return

        # Verify game access
        game = await verify_game_access(db, game_id, user, require_owner=True)
        if not game:
            await websocket.send_json({"type": "error", "message": "Game not found"})
            await websocket.close()
            return

        # Register in room
        room = manager.get_or_create_room(game_id)
        if room.host:
            await websocket.send_json({"type": "error", "message": "Host already connected"})
            await websocket.close()
            return

        room.host = websocket

        # Send current game state (directly from JSONB columns)
        game_state = {
            "discovered_links": [
                {"source": dl["source"], "target": dl["target"]}
                for dl in (game.discovered_links or [])
            ],
            "node_positions": game.node_positions or {},
            "tags": game.tags or {},
        }
        await websocket.send_json({"type": "game_state", "state": game_state})

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "pong":
                    continue

                elif msg_type == "visual_state":
                    # Store last visual state for late-joining viewers
                    room.last_visual_state = data

                    # Broadcast to viewers
                    await manager.broadcast_to_viewers(game_id, data)

                elif msg_type == "positions_update":
                    positions = data.get("positions", {})

                    # Update JSONB column (merge with existing)
                    # Refetch game to get current state
                    result = await db.execute(select(Game).where(Game.id == game_id))
                    game = result.scalar_one_or_none()
                    if game:
                        current_positions = dict(game.node_positions or {})
                        current_positions.update(positions)
                        game.node_positions = current_positions
                        await db.commit()

                    # Broadcast to viewers
                    await manager.broadcast_to_viewers(game_id, data)

                elif msg_type == "tag_update":
                    zone = data.get("zone")
                    tags = data.get("tags", [])

                    # Update JSONB column
                    result = await db.execute(select(Game).where(Game.id == game_id))
                    game = result.scalar_one_or_none()
                    if game:
                        current_tags = dict(game.tags or {})
                        if tags:
                            current_tags[zone] = tags
                        else:
                            current_tags.pop(zone, None)
                        game.tags = current_tags
                        await db.commit()

                    # Broadcast to all (including mod if connected)
                    await manager.broadcast_to_all(game_id, data, exclude=websocket)

                elif msg_type == "manual_discovery":
                    source = data.get("source")
                    target = data.get("target")

                    if source and target:
                        propagated = await propagate_discovery(
                            db, game_id, source, target, discovered_by="manual"
                        )
                        await db.commit()

                        # Broadcast to all
                        await manager.broadcast_to_all(
                            game_id,
                            {"type": "discovery", "propagated": propagated},
                            exclude=websocket,
                        )

        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"Host connection error: {e}")
        finally:
            heartbeat_task.cancel()
            room.host = None
            manager.cleanup_room(game_id)


# =============================================================================
# Viewer WebSocket Handler
# =============================================================================


async def handle_viewer_connection(websocket: WebSocket, game_id: UUID):
    """Handle viewer WebSocket connection (no auth required)."""
    await websocket.accept()

    async with async_session() as db:
        # Verify game exists
        game = await verify_game_access(db, game_id)
        if not game:
            await websocket.send_json({"type": "error", "message": "Game not found"})
            await websocket.close()
            return

        # Check viewer limit
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

        # Register viewer
        room.viewers.append(websocket)

        # Send current state
        if room.last_visual_state:
            await websocket.send_json(room.last_visual_state)
        else:
            # No host connected yet, send basic game info
            await websocket.send_json({"type": "waiting", "message": "Waiting for host to connect"})

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "pong":
                    continue
                # Viewers don't send other messages

        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"Viewer connection error: {e}")
        finally:
            heartbeat_task.cancel()
            if websocket in room.viewers:
                room.viewers.remove(websocket)
            manager.cleanup_room(game_id)
