"""
Viewer WebSocket client handler.
"""

import logging
from uuid import UUID

from fastapi import WebSocket

from fogvizu.config import settings
from fogvizu.database import async_session
from fogvizu.websocket.auth import verify_game_access
from fogvizu.websocket.base import Client, build_game_state
from fogvizu.websocket.manager import manager

logger = logging.getLogger(__name__)


class ViewerClient(Client):
    """Client for viewers (read-only, no auth required)."""

    def _register_handlers(self) -> dict[str, callable]:
        return {
            "pong": self._handle_pong,
        }

    async def _handle_pong(self, data: dict):
        """Handle pong response."""

    @classmethod
    async def handle_connection(cls, websocket: WebSocket, game_id: UUID):
        """Handle viewer WebSocket connection (no auth required)."""
        # Rate limiting check before accepting connection
        client_ip = websocket.client.host if websocket.client else "unknown"
        if not manager.check_rate_limit(client_ip):
            await websocket.accept()
            await websocket.send_json(
                {"type": "error", "message": "Too many connections, try again later"}
            )
            await websocket.close(code=1008)  # Policy violation
            return

        await websocket.accept()

        async with async_session() as db:
            game = await verify_game_access(db, game_id)
            if not game:
                await websocket.send_json({"type": "error", "message": "Game not found"})
                await websocket.close()
                return

            # Build game state from DB (source of truth for discoveries)
            game_state = build_game_state(game)

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

        # Send game state from DB (discoveries are source of truth)
        await client.send({"type": "game_state", "state": game_state})

        # Send visual state from host (viewport, highlights, etc.)
        if room.last_visual_state:
            await client.send(room.last_visual_state)
        elif not room.host:
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
