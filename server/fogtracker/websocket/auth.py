"""
WebSocket authentication helpers.
"""

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import func, or_, select, update

from fogtracker.database import Game, User, async_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def authenticate_ws(
    websocket: WebSocket, db: "AsyncSession", send_auth_ok: bool = True
) -> User | None:
    """Wait for auth message and validate token.

    Args:
        websocket: The WebSocket connection
        db: Database session
        send_auth_ok: If True, send auth_ok immediately. If False, caller is
            responsible for sending auth_ok (useful when extra data needs to
            be included, e.g., stats).
    """
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
        if send_auth_ok:
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


async def update_last_seen(user_id: int) -> None:
    """Update user's last_seen_at timestamp."""
    try:
        async with async_session() as db:
            await db.execute(update(User).where(User.id == user_id).values(last_seen_at=func.now()))
            await db.commit()
    except Exception as e:
        logger.warning("Failed to update last_seen_at for user %d: %s", user_id, e)
