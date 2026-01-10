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
    source_id: str | None = None  # Source zone_key (internal identifier from fog.txt)
    target: str = Field(..., max_length=255)  # Target zone name (for display)
    target_id: str | None = None  # Target zone_key (internal identifier from fog.txt)
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

    id: str  # zone_key (internal identifier from fog.txt)
    name: str | None = None  # Zone display name (optional for backward compat during migration)
    is_boss: bool = False
    scaling: str | None = None


ZonesById = dict[str, Zone]


# =============================================================================
# User
# =============================================================================


class UserPublic(BaseModel):
    """Public user info (no sensitive data)."""

    username: str
    display_name: str | None
    avatar_url: str | None


class UserWithStatus(BaseModel):
    """User info with connection status."""

    username: str
    display_name: str | None
    avatar_url: str | None
    mod_connected: bool = False  # True if mod connected to one of their games
    host_connected: bool = False  # True if host web connected to one of their games
    viewer_count: int = 0  # Total viewers across all their games
    active_game_id: UUID | None = None  # ID of game with mod connected (for direct link)


class UsersListResponse(BaseModel):
    """Response for users listing."""

    users: list[UserWithStatus]


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
    zones: ZonesById


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
    host_connected: bool = False
    viewer_count: int = 0
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


class GameStats(BaseModel):
    """Game statistics from the mod (runes, kindling, deaths, play time)."""

    great_runes: list[str] = Field(default_factory=list)  # ["Godrick", "Radahn", ...]
    kindling_count: int = 0
    death_count: int = 0
    play_time_ms: int = 0  # In-game time in milliseconds


class GameFull(BaseModel):
    """Full game state (for viewers)."""

    id: UUID
    seed: int
    label: str | None
    starting_zone_id: str | None
    zone_links: list[ZoneLink]
    zones: ZonesById
    discovered_zone_links: list[DiscoveredZoneLinkResponse]
    # discovered_nodes removed - client deduces from discovered_zone_links + zone_links
    node_positions: dict[str, NodePositionResponse]
    tags: dict[str, list[str]]
    game_stats: GameStats = Field(default_factory=GameStats)
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

    source_id: str  # Source zone_key
    target_id: str  # Target zone_key
    link_id: str | None = None  # Optional: specific link UUID (for parallel links)


class PropagatedLink(BaseModel):
    """A propagated link from discovery."""

    source_name: str
    source_id: str
    target_name: str
    target_id: str


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

    zone_id: str  # zone_key


class UndiscoveryResponse(BaseModel):
    """Response after undiscovering a zone."""

    removed: list[str]  # Zones that were undiscovered
    discovered_zone_links: list[DiscoveredZoneLink]
    discovery_count: int
    total_zones: int


# =============================================================================
# Tags
# =============================================================================


class TagUpdate(BaseModel):
    """Request body for updating tags on a zone."""

    zone_id: str  # zone_key
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
    zone_id: str  # zone_key
    tags: list[str]


class WSManualDiscoveryMessage(BaseModel):
    """Manual discovery from host (clicked placeholder)."""

    type: str = "manual_discovery"
    source_id: str  # Source zone_key
    target_id: str  # Target zone_key
