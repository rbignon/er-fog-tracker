"""
WebSocket connection manager and game rooms.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import WebSocket

if TYPE_CHECKING:
    from fogvizu.websocket.host import HostClient
    from fogvizu.websocket.mod import ModClient
    from fogvizu.websocket.viewer import ViewerClient

logger = logging.getLogger(__name__)


@dataclass
class GameRoom:
    """Tracks all connections for a game."""

    game_id: UUID
    mod: "ModClient | None" = None
    host: "HostClient | None" = None
    viewers: list["ViewerClient"] = field(default_factory=list)
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
