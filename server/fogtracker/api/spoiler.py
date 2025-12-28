"""
Spoiler log parsing API routes.

Public endpoint (no auth) for parsing spoiler logs.
Used by the offline mode in the frontend.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from fogtracker.models import Zone, ZoneLink
from fogtracker.spoiler_parser import (
    SpoilerParseError,
    enrich_connections_with_zone_keys,
    parse_spoiler_log,
)
from fogtracker.zone_resolver import get_resolver

router = APIRouter(prefix="/spoiler", tags=["spoiler"])


class SpoilerParseRequest(BaseModel):
    """Request body for parsing a spoiler log."""

    spoiler_log: str = Field(description="Full spoiler log content")


class SpoilerParseResponse(BaseModel):
    """Response with parsed spoiler log data."""

    seed: int
    zones: list[dict]
    zone_links: list[dict]


@router.post("/parse", response_model=SpoilerParseResponse)
async def parse_spoiler(data: SpoilerParseRequest):
    """
    Parse a spoiler log and return structured data.

    This endpoint is public (no auth required) and does not persist anything.
    Used by the frontend's offline mode.
    """
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
            required_item=conn.required_item,
            required_item_from=conn.required_item_from,
            is_one_way=conn.is_one_way,
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

    return SpoilerParseResponse(
        seed=parsed.seed,
        zones=zones,
        zone_links=zone_links,
    )
