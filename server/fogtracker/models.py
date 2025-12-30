"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# Zone Link (from spoiler log)
# =============================================================================


class ZoneLink(BaseModel):
    """A link between two zones (fog gate connection)."""

    id: str | None = None  # Unique identifier for this link
    source: str = Field(..., max_length=255)  # Source zone name (for display)
    source_id: str | None = None  # Source zone UUID
    source_key: str | None = Field(default=None, max_length=255)  # Internal zone key
    target: str = Field(..., max_length=255)  # Target zone name (for display)
    target_id: str | None = None  # Target zone UUID
    target_key: str | None = Field(default=None, max_length=255)  # Internal zone key
    type: str = Field(pattern="^(random|preexisting)$")
    source_details: str | None = Field(default=None, max_length=500)
    target_details: str | None = Field(default=None, max_length=500)
    required_item: str | None = Field(default=None, max_length=255)  # Required item name
    required_item_from: str | None = Field(default=None, max_length=2000)  # Zones where item found
    is_one_way: bool = False  # True for sending gates, coffins, drop-downs, etc.


# Keep ZonePair as alias for backward compatibility during transition
ZonePair = ZoneLink


class Zone(BaseModel):
    """Zone metadata (node info from spoiler log)."""

    id: str  # UUID
    name: str | None = None  # Zone display name (optional for backward compat during migration)
    is_boss: bool = False
    scaling: str | None = None


# =============================================================================
# User
# =============================================================================


class UserPublic(BaseModel):
    """Public user info (no sensitive data)."""

    username: str
    display_name: str | None
    avatar_url: str | None


class UserMe(BaseModel):
    """Current user info including API token."""

    id: int
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    api_token: str
    mod_token: str


# =============================================================================
# Game
# =============================================================================


class GameCreate(BaseModel):
    """Request body for creating a game (from web dashboard)."""

    seed: int
    label: str | None = Field(default=None, max_length=200)
    zone_links: list[ZoneLink]
    zones: list[Zone] | None = None


class GameCreateResponse(BaseModel):
    """Response after creating a game."""

    game_id: UUID
    created: bool


class GameSummary(BaseModel):
    """Game summary for listings."""

    id: UUID
    seed: int
    label: str | None
    discovery_count: int
    total_zones: int
    mod_connected: bool = False
    created_at: datetime
    updated_at: datetime


class DiscoveredZoneLinkResponse(BaseModel):
    """A discovered zone link (for API responses)."""

    zone_link_id: str  # Unique link identifier
    discovered_at: datetime | str | None = None  # Can be datetime or ISO string from JSONB
    discovered_by: str | None = None


# Keep old name as alias for backward compatibility
DiscoveredLinkResponse = DiscoveredZoneLinkResponse


class NodePositionResponse(BaseModel):
    """A node position."""

    x: float
    y: float


class GameFull(BaseModel):
    """Full game state (for viewers)."""

    id: UUID
    seed: int
    label: str | None
    zone_links: list[ZoneLink]
    zones: list[Zone] | None = None
    discovered_zone_links: list[DiscoveredZoneLinkResponse]
    # discovered_nodes removed - client deduces from discovered_zone_links + zone_links
    node_positions: dict[str, NodePositionResponse]
    tags: dict[str, list[str]]
    discovery_count: int
    total_zones: int
    created_at: datetime
    updated_at: datetime


class GameUpdate(BaseModel):
    """Request body for updating a game."""

    label: str | None = Field(default=None, max_length=200)


class GameListResponse(BaseModel):
    """Response for game listings."""

    games: list[GameSummary]


# =============================================================================
# Discovery
# =============================================================================


class DiscoveryCreate(BaseModel):
    """Request body for creating a discovery."""

    source: str
    target: str
    link_id: str | None = None  # Optional: specific link UUID (for parallel links)


class PropagatedLink(BaseModel):
    """A propagated link from discovery."""

    source: str
    target: str


class DiscoveredZoneLink(BaseModel):
    """A discovered zone link with metadata."""

    zone_link_id: str  # Unique link identifier
    discovered_at: str | None = None
    discovered_by: str | None = None


# Keep old name as alias
DiscoveredLink = DiscoveredZoneLink


class DiscoveryResponse(BaseModel):
    """Response after creating a discovery."""

    propagated: list[PropagatedLink]
    discovered_zone_links: list[DiscoveredZoneLink]
    discovery_count: int
    total_zones: int


class UndiscoveryRequest(BaseModel):
    """Request body for undiscovering a zone."""

    zone: str


class UndiscoveryResponse(BaseModel):
    """Response after undiscovering a zone."""

    removed: list[str]  # Zones that were undiscovered
    discovered_zone_links: list[DiscoveredZoneLink]


# =============================================================================
# Tags
# =============================================================================


class TagUpdate(BaseModel):
    """Request body for updating tags on a zone."""

    zone: str
    tags: list[str]


# =============================================================================
# WebSocket Messages
# =============================================================================


class WSAuthMessage(BaseModel):
    """WebSocket authentication message."""

    type: str = "auth"
    token: str


class WSDiscoveryMessage(BaseModel):
    """WebSocket discovery message from mod."""

    type: str = "discovery"
    source: str
    target: str


class WSVisualStateNode(BaseModel):
    """Node visual state."""

    x: float
    y: float
    highlighted: bool = False
    dimmed: bool = False
    frontier_highlight: bool = False
    access_highlight: bool = False
    is_placeholder: bool = False


class WSVisualStateLink(BaseModel):
    """Link visual state."""

    highlighted: bool = False
    dimmed: bool = False
    frontier_highlight: bool = False


class WSViewport(BaseModel):
    """Viewport state."""

    x: float
    y: float
    k: float
    width: int
    height: int


class WSVisualStateMessage(BaseModel):
    """Full visual state from host."""

    type: str = "visual_state"
    viewport: WSViewport
    selected_node: str | None = None
    frontier_highlight: bool = False
    exploration_mode: bool = True
    nodes: dict[str, WSVisualStateNode]
    links: dict[str, WSVisualStateLink]


class WSPositionsUpdateMessage(BaseModel):
    """Positions update from host (lighter than full visual state)."""

    type: str = "positions_update"
    positions: dict[str, NodePositionResponse]


class WSTagUpdateMessage(BaseModel):
    """Tag update message."""

    type: str = "tag_update"
    zone: str
    tags: list[str]


class WSManualDiscoveryMessage(BaseModel):
    """Manual discovery from host (clicked placeholder)."""

    type: str = "manual_discovery"
    source: str
    target: str
