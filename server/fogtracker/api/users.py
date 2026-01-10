"""
User routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fogtracker.auth import get_user_by_username
from fogtracker.database import Game, User, get_db
from fogtracker.game_logic import compute_discovery_stats
from fogtracker.models import (
    GameListResponse,
    GameSummary,
    UserPublic,
    UsersListResponse,
    UserWithStatus,
)
from fogtracker.websocket.manager import manager as ws_manager

router = APIRouter()


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
):
    """List all users who have at least one game, with connection status."""
    # Get all users who have at least one non-deleted game
    result = await db.execute(
        select(User)
        .join(Game, Game.user_id == User.id)
        .where(Game.deleted_at.is_(None))
        .distinct()
        .options(selectinload(User.games))
    )
    users = result.scalars().all()

    # Build response with connection status
    users_with_status = []
    for user in users:
        # Get non-deleted game IDs for this user
        game_ids = [g.id for g in user.games if g.deleted_at is None]

        # Check connection status from WebSocket manager
        mod_connected = False
        host_connected = False
        viewer_count = 0
        active_game_id = None

        for game_id in game_ids:
            room = ws_manager.rooms.get(game_id)
            if room:
                if room.mod is not None:
                    mod_connected = True
                    active_game_id = game_id
                if room.host is not None:
                    host_connected = True
                viewer_count += len(room.viewers)

        users_with_status.append(
            UserWithStatus(
                username=user.twitch_username,
                display_name=user.twitch_display_name,
                avatar_url=user.twitch_avatar_url,
                mod_connected=mod_connected,
                host_connected=host_connected,
                viewer_count=viewer_count,
                active_game_id=active_game_id,
            )
        )

    # Sort: mod_connected first, then by display_name (case-insensitive)
    users_with_status.sort(
        key=lambda u: (
            not u.mod_connected,  # False (connected) comes before True (not connected)
            (u.display_name or u.username).lower(),
        )
    )

    return UsersListResponse(users=users_with_status)


@router.get("/users/{username}", response_model=UserPublic)
async def get_user_public(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """Get public user info by username."""
    user = await get_user_by_username(db, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserPublic(
        username=user.twitch_username,
        display_name=user.twitch_display_name,
        avatar_url=user.twitch_avatar_url,
    )


@router.get("/users/{username}/games", response_model=GameListResponse)
async def get_user_games_public(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """Get public list of user's games."""
    user = await get_user_by_username(db, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Get games
    result = await db.execute(
        select(Game)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
        .order_by(Game.updated_at.desc())
    )

    games = []
    for game in result.scalars().all():
        discovered_zone_links = game.discovered_zone_links or []
        stats = compute_discovery_stats(game.zone_links, discovered_zone_links, game.zones)

        # Check connection status from WebSocket manager
        room = ws_manager.rooms.get(game.id)
        mod_connected = room.mod is not None if room else False
        host_connected = room.host is not None if room else False
        viewer_count = len(room.viewers) if room else 0

        games.append(
            GameSummary(
                id=game.id,
                seed=game.seed,
                label=game.label,
                discovery_count=stats["discovered"],
                total_zones=stats["total"],
                mod_connected=mod_connected,
                host_connected=host_connected,
                viewer_count=viewer_count,
                created_at=game.created_at,
                updated_at=game.updated_at,
            )
        )

    return GameListResponse(games=games)
