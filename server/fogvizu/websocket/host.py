"""
Host (streamer browser) WebSocket client handler.
"""

import contextlib
import logging
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from fogvizu.database import Game, async_session
from fogvizu.game_logic import propagate_discovery
from fogvizu.websocket.auth import authenticate_ws, verify_game_access
from fogvizu.websocket.base import Client, build_game_state
from fogvizu.websocket.manager import manager
from fogvizu.zone_matching import compute_discovery_stats, expand_discovered_links

logger = logging.getLogger(__name__)


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

            # Refetch game to get full discovered_zone_links
            result = await db.execute(select(Game).where(Game.id == self.game_id))
            game = result.scalar_one_or_none()

        if game:
            expanded_links = expand_discovered_links(
                game.discovered_zone_links or [], game.zone_links or []
            )
            stats = compute_discovery_stats(game.zone_links or [], game.discovered_zone_links or [])
            await manager.broadcast_to_all(
                self.game_id,
                {
                    "type": "discovery",
                    "propagated": propagated,
                    "discovered_zone_links": expanded_links,
                    "stats": stats,
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
            game_state = build_game_state(game)
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
