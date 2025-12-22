"""
User routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.auth import get_user_by_username
from fogvizu.database import Game, get_db
from fogvizu.game_logic import compute_discovery_stats
from fogvizu.models import GameListResponse, GameSummary, UserPublic

router = APIRouter()


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
        discovered_links = game.discovered_links or []
        stats = compute_discovery_stats(game.zone_pairs, discovered_links)

        games.append(
            GameSummary(
                id=game.id,
                seed=game.seed,
                label=game.label,
                discovery_count=stats["discovered"],
                total_zones=stats["total"],
                created_at=game.created_at,
                updated_at=game.updated_at,
            )
        )

    return GameListResponse(games=games)
