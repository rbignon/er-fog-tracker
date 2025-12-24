"""
Mod/Launcher API routes.

These endpoints are authenticated via mod_token (not api_token).
Used by the game mod and launcher application.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.auth import get_current_user_by_mod_token
from fogvizu.config import settings
from fogvizu.database import Game, User, get_db
from fogvizu.game_logic import compute_discovery_stats
from fogvizu.models import GameCreateResponse, GameListResponse, GameSummary, Zone, ZoneLink
from fogvizu.spoiler_parser import (
    SpoilerParseError,
    enrich_connections_with_zone_keys,
    parse_spoiler_log,
)
from fogvizu.websocket import manager as ws_manager
from fogvizu.zone_resolver import get_resolver

router = APIRouter(prefix="/mod", tags=["mod"])


# =============================================================================
# Models
# =============================================================================


class ModUserInfo(BaseModel):
    """User info returned to mod/launcher."""

    username: str
    display_name: str | None


class ModGameCreate(BaseModel):
    """Request body for creating a game from launcher."""

    spoiler_log: str = Field(description="Full spoiler log content")
    label: str | None = Field(default=None, max_length=200)
    entity_mapping: dict | None = Field(
        default=None,
        description="Optional EMEVD entity mapping from launcher (dest_entity -> {source_map, dest_map, source_entity})",
    )


# =============================================================================
# Routes
# =============================================================================


@router.get("/me", response_model=ModUserInfo)
async def get_mod_user(
    user: User = Depends(get_current_user_by_mod_token),
):
    """Get current user info (validate mod token)."""
    return ModUserInfo(
        username=user.twitch_username,
        display_name=user.twitch_display_name,
    )


@router.get("/games", response_model=GameListResponse)
async def list_games(
    user: User = Depends(get_current_user_by_mod_token),
    db: AsyncSession = Depends(get_db),
):
    """List user's games (for launcher game selection)."""
    result = await db.execute(
        select(Game)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
        .order_by(Game.updated_at.desc())
    )

    games = []
    for game in result.scalars().all():
        discovered_zone_links = game.discovered_zone_links or []
        stats = compute_discovery_stats(game.zone_links, discovered_zone_links)

        games.append(
            GameSummary(
                id=game.id,
                seed=game.seed,
                label=game.label,
                discovery_count=stats["discovered"],
                total_zones=stats["total"],
                mod_connected=ws_manager.is_mod_connected(game.id),
                created_at=game.created_at,
                updated_at=game.updated_at,
            )
        )

    return GameListResponse(games=games)


@router.post("/games", response_model=GameCreateResponse)
async def create_game(
    data: ModGameCreate,
    user: User = Depends(get_current_user_by_mod_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a new game from spoiler log (called by launcher)."""
    # Check game limit
    result = await db.execute(
        select(func.count(Game.id)).where(Game.user_id == user.id).where(Game.deleted_at.is_(None))
    )
    game_count = result.scalar_one()

    if game_count >= settings.max_games_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum games per user ({settings.max_games_per_user}) reached",
        )

    # Parse spoiler log
    try:
        parsed = parse_spoiler_log(data.spoiler_log)
    except SpoilerParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid spoiler log: {e}",
        ) from None

    # Enrich connections with zone_keys from fog.txt
    resolver = get_resolver()
    enriched_connections = enrich_connections_with_zone_keys(parsed.connections, resolver)

    # Convert parsed data to zone_links format
    zone_links = [
        ZoneLink(
            id=conn.id,
            source=conn.source,
            source_id=conn.source_id,
            source_key=conn.source_key,
            target=conn.target,
            target_id=conn.target_id,
            target_key=conn.target_key,
            type=conn.conn_type,
            source_details=conn.source_details or None,
            target_details=conn.target_details or None,
            is_inherently_one_way=conn.is_inherently_one_way,
        ).model_dump()
        for conn in enriched_connections
    ]

    # Convert zones
    zones = [
        Zone(
            id=zone.id,
            name=zone.name,
            is_boss=zone.is_boss,
            scaling=zone.scaling,
        ).model_dump()
        for zone in parsed.zones
    ]

    # Create new game
    game = Game(
        user_id=user.id,
        seed=parsed.seed,
        label=data.label,
        zone_links=zone_links,
        zones=zones,
        entity_mapping=data.entity_mapping,
        discovered_zone_links=[],
        node_positions={},
        tags={},
    )
    db.add(game)
    await db.flush()

    return GameCreateResponse(game_id=game.id, created=True)


@router.delete("/games/{game_id}")
async def delete_game(
    game_id: str,
    user: User = Depends(get_current_user_by_mod_token),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a game (called by launcher)."""
    from uuid import UUID

    try:
        game_uuid = UUID(game_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid game ID format",
        ) from None

    result = await db.execute(
        select(Game)
        .where(Game.id == game_uuid)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    from datetime import UTC, datetime

    game.deleted_at = datetime.now(UTC)
    await db.flush()

    return {"status": "ok"}
