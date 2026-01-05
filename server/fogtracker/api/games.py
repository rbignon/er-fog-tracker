"""
Game routes.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from fogtracker.auth import get_current_user
from fogtracker.config import settings
from fogtracker.database import Game, User, get_db
from fogtracker.game_logic import (
    compute_discovery_stats,
    format_discovery_summary,
    format_undiscovery_summary,
    propagate_discovery,
)
from fogtracker.models import (
    DiscoveredZoneLink,
    DiscoveredZoneLinkResponse,
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
    ZoneLink,
)
from fogtracker.websocket import manager as ws_manager
from fogtracker.zone_matching import build_zone_pairs_index, get_zone_link_id, undiscover_zone

logger = logging.getLogger(__name__)

router = APIRouter()


def _expand_discovered_zone_link(dl: dict, zp_index: dict[str, dict]) -> tuple[str, str, str]:
    """Expand a discovered zone link to (zone_link_id, source, target)."""
    zone_link_id = get_zone_link_id(dl)
    zp = zp_index.get(zone_link_id)
    if zp:
        return zone_link_id, zp["source"], zp["target"]
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
        zone_links=[zl.model_dump() for zl in data.zone_links],
        zones={zone_id: z.model_dump() for zone_id, z in data.zones.items()},
        discovered_zone_links=[],
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

    # Get zone_links and discovered_zone_links
    zone_links = game.zone_links or []
    discovered_zone_links = game.discovered_zone_links or []

    # Build zone_links index to expand zone_link_ids
    zp_index = build_zone_pairs_index(zone_links)

    # Compute discovery stats
    stats = compute_discovery_stats(zone_links, discovered_zone_links, game.zones)

    # Parse node positions
    node_positions = {
        node_id: NodePositionResponse(x=pos["x"], y=pos["y"])
        for node_id, pos in (game.node_positions or {}).items()
    }

    # Parse zones metadata
    zones = {zone_id: Zone(**zone) for zone_id, zone in (game.zones or {}).items()}

    # Build discovered_zone_links response (just zone_link_id + metadata)
    response_links = []
    for dl in discovered_zone_links:
        zone_link_id = get_zone_link_id(dl)
        if zone_link_id and zone_link_id in zp_index:
            response_links.append(
                DiscoveredZoneLinkResponse(
                    zone_link_id=zone_link_id,
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    return GameFull(
        id=game.id,
        seed=game.seed,
        label=game.label,
        starting_zone_id=game.starting_zone_id,
        zone_links=[ZoneLink(**zl) for zl in zone_links],
        zones=zones,
        discovered_zone_links=response_links,
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
        discovered_zone_links = game.discovered_zone_links or []
        stats = compute_discovery_stats(game.zone_links, discovered_zone_links, game.zones)

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

    discovered_zone_links = game.discovered_zone_links or []
    stats = compute_discovery_stats(game.zone_links, discovered_zone_links, game.zones)

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
    # Verify game exists
    result = await db.execute(
        select(Game).where(Game.id == game_id).where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    # Verify user is the owner (viewers cannot create discoveries)
    if game.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the game owner can create discoveries",
        )

    # Propagate discovery
    discovery_result = await propagate_discovery(
        db, game_id, data.source_id, data.target_id, discovered_by="web", link_id=data.link_id
    )
    propagated = discovery_result.all_links()

    # Refresh game to get updated discovered_zone_links
    await db.refresh(game)
    all_links = game.discovered_zone_links or []
    zone_links = game.zone_links or []
    zp_index = build_zone_pairs_index(zone_links)

    # Build response with zone_link_id only (no source/target duplication)
    response_links = []
    for dl in all_links:
        zone_link_id = get_zone_link_id(dl)
        if zone_link_id and zone_link_id in zp_index:
            response_links.append(
                DiscoveredZoneLink(
                    zone_link_id=zone_link_id,
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    # Compute discovery stats
    stats = compute_discovery_stats(zone_links, all_links, game.zones)

    # Log discovery summary
    if discovery_result.total_count() > 0:
        summary = format_discovery_summary(
            discovery_result,
            discovered_by="web",
            total_discovered=stats["discovered"],
            total_links=stats["total"],
        )
        for line in summary.split("\n"):
            logger.info(line)

    # Broadcast to viewers via WebSocket (host already has the response)
    if propagated:
        # Convert to dict format for WebSocket broadcast
        links_ws = [{"zone_link_id": dl.zone_link_id} for dl in response_links]
        await ws_manager.broadcast_to_viewers(
            game_id,
            {
                "type": "discovery",
                "propagated": propagated,
                "discovered_zone_links": links_ws,
                "stats": stats,
            },
        )

    return DiscoveryResponse(
        propagated=[PropagatedLink(**p) for p in propagated],
        discovered_zone_links=response_links,
        discovery_count=stats["discovered"],
        total_zones=stats["total"],
    )


@router.post("/games/{game_id}/undiscoveries", response_model=UndiscoveryResponse)
async def create_undiscovery(
    game_id: UUID,
    data: UndiscoveryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Undiscover a zone and cascade to unreachable zones."""
    # Verify game exists
    result = await db.execute(
        select(Game).where(Game.id == game_id).where(Game.deleted_at.is_(None))
    )
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    # Verify user is the owner (viewers cannot undiscover zones)
    if game.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the game owner can undiscover zones",
        )

    # Undiscover the zone and cascade
    discovered_zone_links = game.discovered_zone_links or []
    zone_links = game.zone_links or []
    starting_zone_id = game.starting_zone_id or "chapel_start"
    new_links, removed_zones = undiscover_zone(
        discovered_zone_links, data.zone_id, zone_links, starting_zone_id
    )

    # Update game
    game.discovered_zone_links = new_links
    flag_modified(game, "discovered_zone_links")
    await db.flush()

    # Build response with zone_link_id only
    zp_index = build_zone_pairs_index(zone_links)
    response_links = []
    for dl in new_links:
        zone_link_id = get_zone_link_id(dl)
        if zone_link_id and zone_link_id in zp_index:
            response_links.append(
                DiscoveredZoneLink(
                    zone_link_id=zone_link_id,
                    discovered_at=dl.get("discovered_at"),
                    discovered_by=dl.get("discovered_by"),
                )
            )

    # Compute stats and log summary
    stats = compute_discovery_stats(zone_links, new_links, game.zones)
    if removed_zones:
        summary = format_undiscovery_summary(
            data.zone_id,
            removed_zones,
            total_discovered=stats["discovered"],
            total_links=stats["total"],
        )
        for line in summary.split("\n"):
            logger.info(line)

    # Broadcast to viewers via WebSocket
    if removed_zones:
        links_ws = [{"zone_link_id": dl.zone_link_id} for dl in response_links]
        await ws_manager.broadcast_to_viewers(
            game_id,
            {
                "type": "discovery",  # Reuse discovery type - sends full state
                "propagated": [],
                "discovered_zone_links": links_ws,
                "stats": stats,
            },
        )

    return UndiscoveryResponse(
        removed=removed_zones,
        discovered_zone_links=response_links,
        discovery_count=stats["discovered"],
        total_zones=stats["total"],
    )
