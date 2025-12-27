# Communication Protocol

This document describes the REST API endpoints and WebSocket protocol used for communication between components.

## Roles

### Mod
- **In-game DLL** injected into Elden Ring
- **Authenticated** via `mod_token`
- **Capabilities**:
  - Send discovery events when player traverses fog gates
  - Receive zone info and available exits
  - Update tags on zones

### Host
- **Streamer's browser** viewing their own game
- **Authenticated** via `api_token` (from Twitch OAuth)
- **Capabilities**:
  - Full control of the graph visualization
  - Discover/undiscover zones manually
  - Move nodes, change exploration mode
  - Visual state is broadcast to viewers

### Viewer
- **Read-only browser** watching a streamer's game
- **No authentication required** (public access)
- **Capabilities**:
  - Receive and mirror host's visual state
  - No local modifications allowed

## REST API

### Authentication Endpoints

#### `GET /auth/twitch`
Redirect to Twitch OAuth login.

**Response**: 302 redirect to Twitch

#### `GET /auth/twitch/callback`
Handle Twitch OAuth callback.

**Query Parameters**:
- `code`: OAuth authorization code
- `state`: CSRF protection token

**Response**: 302 redirect to `/dashboard?token={api_token}`

#### `GET /auth/me`
Get current user info.

**Headers**: `Authorization: Bearer {api_token}`

**Response**:
```json
{
  "id": 123,
  "twitch_username": "streamer",
  "twitch_display_name": "Streamer",
  "twitch_avatar_url": "https://...",
  "api_token": "abc123...",
  "mod_token": "xyz789..."
}
```

#### `POST /auth/regenerate-mod-token`
Generate a new mod token (invalidates old one).

**Headers**: `Authorization: Bearer {api_token}`

**Response**: Same as `/auth/me`

---

### Mod Endpoints (`/api/mod/*`)

These endpoints use `mod_token` for authentication.

#### `GET /api/mod/me`
Validate mod token and get user info.

**Headers**: `Authorization: Bearer {mod_token}`

**Response**:
```json
{
  "username": "streamer",
  "display_name": "Streamer"
}
```

#### `GET /api/mod/games`
List user's games (for launcher game selection).

**Headers**: `Authorization: Bearer {mod_token}`

**Response**:
```json
{
  "games": [
    {
      "id": "uuid-here",
      "seed": 12345,
      "run_id": "12345_abc123",
      "label": "My Run",
      "discovery_count": 15,
      "total_zones": 100,
      "mod_connected": true,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T12:00:00Z"
    }
  ]
}
```

#### `POST /api/mod/games`
Create a new game from spoiler log.

**Headers**: `Authorization: Bearer {mod_token}`

**Request Body**:
```json
{
  "spoiler_log": "Options and seed:12345 ...",
  "label": "My Run (optional)",
  "entity_mapping": {
    "755890001": {
      "source_map": "m10_01_00_00",
      "dest_map": "m11_05_00_00",
      "source_entity": 755890002
    }
  }
}
```

**Response**:
```json
{
  "game_id": "uuid-here",
  "created": true
}
```

If game already exists (same seed + run_id):
```json
{
  "game_id": "existing-uuid",
  "created": false
}
```

---

### Game Endpoints (`/api/games/*`)

#### `GET /api/games/{game_id}`
Get full game state (public, for viewers).

**Response**:
```json
{
  "id": "uuid",
  "seed": 12345,
  "run_id": "12345_abc123",
  "label": "My Run",
  "zone_links": [...],
  "zones": [...],
  "discovered_zone_links": [
    {"zone_link_id": "uuid", "discovered_at": "...", "discovered_by": "mod"}
  ],
  "node_positions": {"zone_name": {"x": 100, "y": 200}},
  "tags": {"zone_name": ["tag1", "tag2"]},
  "discovery_count": 15,
  "total_zones": 100,
  "created_at": "...",
  "updated_at": "..."
}
```

#### `GET /api/me/games`
List current user's games.

**Headers**: `Authorization: Bearer {api_token}`

#### `PATCH /api/games/{game_id}`
Update game metadata.

**Headers**: `Authorization: Bearer {api_token}`

**Request Body**:
```json
{
  "label": "New Label"
}
```

#### `DELETE /api/games/{game_id}`
Soft-delete a game.

**Headers**: `Authorization: Bearer {api_token}`

#### `POST /api/games/{game_id}/discoveries`
Create a discovery (REST fallback, prefer WebSocket).

**Headers**: `Authorization: Bearer {api_token}`

**Request Body**:
```json
{
  "source": "Zone A",
  "target": "Zone B",
  "link_id": "optional-uuid"
}
```

**Side effect**: Broadcasts a `discovery` message to all connected viewers via WebSocket.

#### `POST /api/games/{game_id}/undiscoveries`
Undiscover a zone and cascade.

**Headers**: `Authorization: Bearer {api_token}`

**Request Body**:
```json
{
  "zone": "Zone Name"
}
```

**Side effect**: Broadcasts a `discovery` message (with updated state) to all connected viewers via WebSocket.

---

## WebSocket Protocol

### Connection URLs

| Client | URL | Auth Method |
|--------|-----|-------------|
| Mod | `/ws/mod/{game_id}` | First message: `{"type": "auth", "token": "{mod_token}"}` |
| Host | `/ws/host/{game_id}` | First message: `{"type": "auth", "token": "{api_token}"}` |
| Viewer | `/ws/viewer/{game_id}` | No auth required |

### Authentication Flow

```
Client                              Server
   │                                   │
   │─────── Connect to /ws/... ───────▶│
   │                                   │
   │◀─────── Connection accepted ──────│
   │                                   │
   │─── {"type": "auth", "token":...} ─▶│
   │                                   │
   │◀─── {"type": "auth_ok", ...} ─────│
   │         or                        │
   │◀─── {"type": "auth_error", ───────│
   │         "message": "..."}         │
```

#### Mod `auth_ok` Response

For mod connections (`/ws/mod/{game_id}`), the `auth_ok` response includes discovery stats:

```json
{
  "type": "auth_ok",
  "stats": {
    "discovered": 15,
    "total": 100
  }
}
```

| Field | Description |
|-------|-------------|
| `stats.discovered` | Number of discovered random links |
| `stats.total` | Total number of random links |

This allows the mod overlay to display accurate progress immediately on connection, without waiting for the first discovery event.

### Heartbeat

Server sends `{"type": "ping"}` periodically (default: 30s).
Client must respond with `{"type": "pong"}`.

Connection is closed if no pong received within 60s.

---

### Mod Messages

#### Mod → Server: `discovery_v2`

Sent when player traverses a fog gate.

```json
{
  "type": "discovery_v2",
  "source_map_id": "m10_01_00_00",
  "source_pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "source_play_region_id": 1048576,
  "target_map_id": "m11_05_00_00",
  "target_pos": {"x": 150.0, "y": 60.0, "z": 180.0},
  "target_play_region_id": 2097152,
  "warp_type": "FOG",
  "destination_entity_id": 755890123
}
```

| Field | Description |
|-------|-------------|
| `source_map_id` | Map ID before warp (format: `mWW_XX_YY_DD`) |
| `source_pos` | Player position before warp |
| `source_play_region_id` | Play region ID (Col) before warp |
| `target_map_id` | Map ID after warp |
| `target_pos` | Player position after warp |
| `target_play_region_id` | Play region ID after warp |
| `warp_type` | Type: `FOG`, `WAYGATE`, `MEDAL`, `COFFIN` |
| `destination_entity_id` | FogMod spawn point entity (755890xxx) |

#### Server → Mod: `discovery_v2_ack`

Acknowledgment with resolved zone info.

```json
{
  "type": "discovery_v2_ack",
  "propagated": [
    {"source": "Zone A", "target": "Zone B"}
  ],
  "resolved": [
    {"source": "Zone A", "target": "Zone B"}
  ],
  "current_zone": "Zone B",
  "exits": [
    {
      "id": "link-uuid",
      "target": "Zone C",
      "description": "after the boss",
      "from_zone": null
    },
    {
      "id": "link-uuid-2",
      "target": "???",
      "description": "near the elevator",
      "from_zone": "Zone B - Interior"
    }
  ],
  "stats": {
    "discovered": 15,
    "total": 100,
    "percent": 15.0
  }
}
```

| Field | Description |
|-------|-------------|
| `propagated` | Links discovered (including preexisting propagation) |
| `resolved` | The specific link that was matched |
| `current_zone` | Zone player arrived in |
| `exits` | Available fog gates from current zone |
| `stats` | Discovery progress |

#### Mod → Server: `zone_query`

Sent after fast travel (grace site teleportation) to request current zone info.

```json
{
  "type": "zone_query",
  "map_id": "m10_01_00_00",
  "pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "play_region_id": 1048576
}
```

| Field | Description |
|-------|-------------|
| `map_id` | Current map ID (format: `mWW_XX_YY_DD`) |
| `pos` | Player position |
| `play_region_id` | Play region ID (Col) for precise resolution |

#### Server → Mod: `zone_query_ack`

Response with resolved zone and exits.

```json
{
  "type": "zone_query_ack",
  "zone": "Limgrave - Church of Elleh",
  "exits": [
    {
      "id": "link-uuid",
      "target": "Zone C",
      "description": "after the boss",
      "from_zone": null
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `zone` | Resolved zone name (null if not found) |
| `exits` | Available fog gates from current zone |

#### Mod → Server: `debug_log`

Debug message for server logging.

```json
{
  "type": "debug_log",
  "message": "SpEffect 4280 activated"
}
```

#### Mod → Server: `tag_update`

Update tags on a zone.

```json
{
  "type": "tag_update",
  "zone": "Zone Name",
  "tags": ["cleared", "important"]
}
```

---

### Host Messages

#### Host → Server: `visual_state`

Broadcast current visual state to viewers.

**Note**: This message contains only visual information (positions, highlights, viewport, selection). Discoveries are NOT included here - the server is the single source of truth for discoveries, synced via dedicated `discovery` messages.

```json
{
  "type": "visual_state",
  "nodes": {
    "Zone A": {
      "classes": ["highlighted", "frontier-highlight"],
      "x": 100,
      "y": 200
    }
  },
  "links": {
    "Zone A|Zone B": {
      "classes": ["dimmed"]
    }
  },
  "viewport": {
    "x": 0,
    "y": 0,
    "scale": 1.0
  },
  "explorationMode": true,
  "frontierMode": true,
  "selectedNode": "Zone A",
  "discoveredCount": 15,
  "totalAreas": 100
}
```

#### Host → Server: `positions_update`

Save node positions to database.

```json
{
  "type": "positions_update",
  "positions": {
    "Zone A": {"x": 100, "y": 200},
    "Zone B": {"x": 150, "y": 250}
  }
}
```

#### Host → Server: `manual_discovery`

Discover a link manually (from web UI).

```json
{
  "type": "manual_discovery",
  "source": "Zone A",
  "target": "Zone B"
}
```

#### Host → Server: `tag_update`

Same as mod tag_update.

---

### Server → Client Messages

#### `discovery`

Broadcast when a discovery is made (from mod or manual).

```json
{
  "type": "discovery",
  "propagated": [
    {"source": "Zone A", "target": "Zone B"}
  ],
  "discovered_zone_links": [
    {"zone_link_id": "uuid"}
  ],
  "stats": {"discovered": 15, "total": 100}
}
```

| Field | Description |
|-------|-------------|
| `propagated` | Links discovered in this event (with source/target for display) |
| `discovered_zone_links` | All discovered links (zone_link_id only, client resolves source/target from its linkIndex) |
| `stats` | Discovery progress |

#### `mod_connected` / `mod_disconnected`

Sent to host when mod connects/disconnects.

```json
{"type": "mod_connected"}
{"type": "mod_disconnected"}
```

#### `game_state`

Sent to host/viewer on initial connection.

```json
{
  "type": "game_state",
  "state": {
    "discovered_zone_links": [
      {"zone_link_id": "uuid"}
    ],
    "node_positions": {...},
    "tags": {...}
  }
}
```

**Note**: `discovered_zone_links` contains only `zone_link_id`. Client resolves `source`/`target` from its `linkIndex` (built from `zone_links` loaded via REST API).

#### `error`

Error message.

```json
{
  "type": "error",
  "message": "Game not found"
}
```

---

## Sequence Diagrams

### Discovery Flow

```
  Player         Mod          Server         Host         Viewers
    │             │              │             │              │
    │ traverse    │              │             │              │
    │ fog gate    │              │             │              │
    │────────────▶│              │             │              │
    │             │              │             │              │
    │             │ discovery_v2 │             │              │
    │             │─────────────▶│             │              │
    │             │              │             │              │
    │             │              │ resolve     │              │
    │             │              │ zones       │              │
    │             │              │             │              │
    │             │              │ store       │              │
    │             │              │ discovery   │              │
    │             │              │             │              │
    │             │ discovery_   │             │              │
    │             │ v2_ack       │             │              │
    │             │◀─────────────│             │              │
    │             │              │             │              │
    │             │              │ discovery   │              │
    │             │              │─────────────▶│              │
    │             │              │             │              │
    │             │              │             │ discovery    │
    │             │              │             │─────────────▶│
    │             │              │             │              │
    │ show exits  │              │             │ update       │ update
    │◀────────────│              │             │ graph        │ graph
    │             │              │             │              │
```

### Viewer Sync Flow

**Two separate channels:**

1. **Visual state** - Host broadcasts positions, highlights, viewport to viewers
2. **Discoveries** - Server broadcasts discoveries to all clients (host + viewers)

```
  Host           Server        Viewer
    │               │             │
    │               │  game_state │  (on connect: initial discoveries)
    │               │────────────▶│
    │               │             │
    │ visual_state  │             │
    │──────────────▶│             │
    │               │ visual_state│
    │               │────────────▶│  apply positions, highlights
    │               │             │
    │               │             │
    │               │  discovery  │  (when mod/host discovers)
    │               │────────────▶│  apply new discoveries
    │               │             │
```

**Key principle**: The server is the single source of truth for discoveries. Viewers receive discoveries from `game_state` (initial load) and `discovery` messages (real-time updates), NOT from the host's `visual_state`.

## Error Handling

### HTTP Errors

| Status | Meaning |
|--------|---------|
| 400 | Bad request (invalid data) |
| 401 | Unauthorized (invalid/missing token) |
| 404 | Resource not found |
| 429 | Rate limited (max games reached) |
| 500 | Server error |

### WebSocket Errors

On authentication failure, server sends `auth_error` then closes connection.

On other errors, server sends `error` message. Connection may remain open.

## Rate Limiting

- Max games per user: 20 (configurable)
- Max viewers per game: 50 (configurable)
- WebSocket heartbeat: 30s (configurable)
