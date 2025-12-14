"""
Game routes.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fogvizu.auth import get_current_user
from fogvizu.config import settings
from fogvizu.database import Game, User, get_db
from fogvizu.game_logic import compute_total_zones, get_discovered_nodes, propagate_discovery
from fogvizu.models import (
    DiscoveredLinkResponse,
    DiscoveryCreate,
    DiscoveryResponse,
    GameCreate,
    GameCreateResponse,
    GameFull,
    GameListResponse,
    GameSummary,
    GameUpdate,
    NodePositionResponse,
    PropagatedLink,
    Zone,
)

router = APIRouter()


# =============================================================================
# Game CRUD
# =============================================================================


@router.post("/games", response_model=GameCreateResponse)
async def create_game(
    data: GameCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new game (called by mod)."""
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

    # Check if game already exists
    result = await db.execute(
        select(Game)
        .where(Game.user_id == user.id)
        .where(Game.seed == data.seed)
        .where(Game.run_id == data.run_id)
        .where(Game.deleted_at.is_(None))
    )
    existing_game = result.scalar_one_or_none()

    if existing_game:
        return GameCreateResponse(game_id=existing_game.id, created=False)

    # Create new game
    game = Game(
        user_id=user.id,
        seed=data.seed,
        run_id=data.run_id,
        label=data.label,
        zone_pairs=[zp.model_dump() for zp in data.zone_pairs],
        zones=[z.model_dump() for z in data.zones] if data.zones else None,
        discovered_links=[],
        node_positions={},
        tags={},
    )
    db.add(game)
    await db.flush()

    return GameCreateResponse(game_id=game.id, created=True)


@router.get("/games/{game_id}", response_model=GameFull)
async def get_game(
    game_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get full game state (public, for viewers)."""
    result = await db.execute(
        select(Game).where(Game.id == game_id).where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    # Compute discovered nodes from discovered_links
    discovered_links = game.discovered_links or []
    discovered_nodes = get_discovered_nodes(discovered_links)

    # Parse node positions
    node_positions = {
        node_id: NodePositionResponse(x=pos["x"], y=pos["y"])
        for node_id, pos in (game.node_positions or {}).items()
    }

    # Parse zones metadata
    zones = [Zone(**z) for z in game.zones] if game.zones else None

    return GameFull(
        id=game.id,
        seed=game.seed,
        run_id=game.run_id,
        label=game.label,
        zone_pairs=game.zone_pairs,
        zones=zones,
        discovered_links=[
            DiscoveredLinkResponse(
                source=dl["source"],
                target=dl["target"],
                discovered_at=dl["discovered_at"],
                discovered_by=dl["discovered_by"],
            )
            for dl in discovered_links
        ],
        discovered_nodes=list(discovered_nodes),
        node_positions=node_positions,
        tags=game.tags or {},
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


@router.get("/me/games", response_model=GameListResponse)
async def get_my_games(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's games."""
    result = await db.execute(
        select(Game)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
        .order_by(Game.updated_at.desc())
    )

    games = []
    for game in result.scalars().all():
        discovered_links = game.discovered_links or []
        total_zones = compute_total_zones(game.zone_pairs)

        games.append(
            GameSummary(
                id=game.id,
                seed=game.seed,
                run_id=game.run_id,
                label=game.label,
                discovery_count=len(discovered_links),
                total_zones=total_zones,
                created_at=game.created_at,
                updated_at=game.updated_at,
            )
        )

    return GameListResponse(games=games)


@router.delete("/games/{game_id}")
async def delete_game(
    game_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a game."""
    result = await db.execute(
        select(Game)
        .where(Game.id == game_id)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    game.deleted_at = datetime.now(UTC)
    await db.flush()

    return {"status": "ok"}


@router.patch("/games/{game_id}", response_model=GameSummary)
async def update_game(
    game_id: UUID,
    data: GameUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update game metadata (label only)."""
    result = await db.execute(
        select(Game)
        .where(Game.id == game_id)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    if data.label is not None:
        game.label = data.label

    await db.flush()

    discovered_links = game.discovered_links or []

    return GameSummary(
        id=game.id,
        seed=game.seed,
        run_id=game.run_id,
        label=game.label,
        discovery_count=len(discovered_links),
        total_zones=compute_total_zones(game.zone_pairs),
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


# =============================================================================
# Discovery (REST fallback)
# =============================================================================


@router.post("/games/{game_id}/discoveries", response_model=DiscoveryResponse)
async def create_discovery(
    game_id: UUID,
    data: DiscoveryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a discovery (REST fallback, prefer WebSocket)."""
    # Verify game exists and belongs to user
    result = await db.execute(
        select(Game)
        .where(Game.id == game_id)
        .where(Game.user_id == user.id)
        .where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    # Propagate discovery
    propagated = await propagate_discovery(
        db, game_id, data.source, data.target, discovered_by="mod"
    )

    return DiscoveryResponse(
        propagated=[PropagatedLink(source=p["source"], target=p["target"]) for p in propagated]
    )
