"""
Base WebSocket client class and helper functions.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from fogvizu.config import settings
from fogvizu.database import Game, User
from fogvizu.zone_matching import get_zone_link_id

logger = logging.getLogger(__name__)


def build_game_state(game: Game) -> dict:
    """Build game state dict from database game object.

    Returns discovered_zone_links with only zone_link_id (no source/target).
    Client resolves source/target from its linkIndex for consistency with REST API.
    """
    zone_links = game.zone_links or []
    zl_ids = {zl["id"] for zl in zone_links if zl.get("id")}

    # Only include zone_link_id (client resolves source/target from linkIndex)
    discovered_links = []
    for dl in game.discovered_zone_links or []:
        zl_id = get_zone_link_id(dl)
        if zl_id and zl_id in zl_ids:
            discovered_links.append({"zone_link_id": zl_id})

    return {
        "discovered_zone_links": discovered_links,
        "node_positions": game.node_positions or {},
        "tags": game.tags or {},
    }


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
