"""
Game routes.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from fogvizu.auth import get_current_user
from fogvizu.config import settings
from fogvizu.database import Game, User, get_db
from fogvizu.game_logic import (
    compute_discovery_stats,
    propagate_discovery,
)
from fogvizu.models import (
    DiscoveredLink,
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
    UndiscoveryRequest,
    UndiscoveryResponse,
    Zone,
)
from fogvizu.websocket import manager as ws_manager
from fogvizu.zone_matching import build_zone_pairs_index, get_discovered_nodes, undiscover_zone

router = APIRouter()


def _expand_discovered_link(dl: dict, zp_index: dict[str, dict]) -> tuple[str, str, str]:
    """Expand a discovered link to (link_id, source, target)."""
    zp = zp_index.get(dl["link_id"])
    if zp:
        return dl["link_id"], zp["source"], zp["destination"]
    return "", "", ""  # Link not found


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

    # Create new game
    game = Game(
        user_id=user.id,
        seed=data.seed,
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
    zone_pairs = game.zone_pairs or []
    discovered_links = game.discovered_links or []
    discovered_nodes = get_discovered_nodes(discovered_links, zone_pairs)

    # Build zone_pairs index to expand link_ids to source/target
    zp_index = build_zone_pairs_index(zone_pairs)

    # Compute discovery stats
    stats = compute_discovery_stats(zone_pairs, discovered_links)

    # Parse node positions
    node_positions = {
        node_id: NodePositionResponse(x=pos["x"], y=pos["y"])
        for node_id, pos in (game.node_positions or {}).items()
    }

    # Parse zones metadata
    zones = [Zone(**z) for z in game.zones] if game.zones else None

    # Expand discovered_links to include source/target for API response
    expanded_links = []
    for dl in discovered_links:
        zp = zp_index.get(dl["link_id"])
        if zp:
            expanded_links.append(
                DiscoveredLinkResponse(
                    link_id=dl["link_id"],
                    source=zp["source"],
                    target=zp["destination"],
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    return GameFull(
        id=game.id,
        seed=game.seed,
        label=game.label,
        zone_pairs=zone_pairs,
        zones=zones,
        discovered_links=expanded_links,
        discovered_nodes=list(discovered_nodes),
        node_positions=node_positions,
        tags=game.tags or {},
        discovery_count=stats["discovered"],
        total_zones=stats["total"],
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
        stats = compute_discovery_stats(game.zone_pairs, discovered_links)

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
    stats = compute_discovery_stats(game.zone_pairs, discovered_links)

    return GameSummary(
        id=game.id,
        seed=game.seed,
        label=game.label,
        discovery_count=stats["discovered"],
        total_zones=stats["total"],
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
        db, game_id, data.source, data.target, discovered_by="web", link_id=data.link_id
    )

    # Refresh game to get updated discovered_links
    await db.refresh(game)
    all_links = game.discovered_links or []
    zone_pairs = game.zone_pairs or []
    zp_index = build_zone_pairs_index(zone_pairs)

    # Build response with expanded links
    expanded_links = []
    for dl in all_links:
        link_id, source, target = _expand_discovered_link(dl, zp_index)
        if source and target:  # Skip broken links
            expanded_links.append(
                DiscoveredLink(
                    link_id=link_id,
                    source=source,
                    target=target,
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    return DiscoveryResponse(
        propagated=[PropagatedLink(source=p["source"], target=p["target"]) for p in propagated],
        discovered_links=expanded_links,
    )


@router.post("/games/{game_id}/undiscoveries", response_model=UndiscoveryResponse)
async def create_undiscovery(
    game_id: UUID,
    data: UndiscoveryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Undiscover a zone and cascade to unreachable zones."""
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

    # Undiscover the zone and cascade
    discovered_links = game.discovered_links or []
    zone_pairs = game.zone_pairs or []
    new_links, removed_zones = undiscover_zone(discovered_links, data.zone, zone_pairs)

    # Update game
    game.discovered_links = new_links
    flag_modified(game, "discovered_links")
    await db.flush()

    # Build response with expanded links
    zp_index = build_zone_pairs_index(zone_pairs)
    expanded_links = []
    for dl in new_links:
        link_id, source, target = _expand_discovered_link(dl, zp_index)
        if source and target:  # Skip broken links
            expanded_links.append(
                DiscoveredLink(
                    link_id=link_id,
                    source=source,
                    target=target,
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    return UndiscoveryResponse(
        removed=removed_zones,
        discovered_links=expanded_links,
    )
