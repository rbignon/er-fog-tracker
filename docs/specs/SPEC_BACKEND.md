# Backend Specification (Revised)

This document describes the backend architecture for er-fog-vizu integration with the Route Tracker mod.

## 1. Overview

### 1.1 Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Source of truth | Server (PostgreSQL) | Single source, no sync conflicts |
| Propagation logic | Server-side | Server has full spoiler log data |
| Visual sync | Full state (positions, highlights, viewport) | Viewer sees exactly what host sees |
| Offline mode | Supported via LocalBackend | Backwards compatibility, testing |
| Overlay (mod) | Deferred to v2 | Focus on core sync first |

### 1.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              MOD (Rust)                                  │
│  - Detects fog traversals                                               │
│  - Sends discovery events to server                                     │
│  - Sends character name as game label                                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTPS + WSS
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            SERVER (Python)                               │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │  REST API   │  │  WebSocket  │  │  Game Logic │  │   PostgreSQL  │  │
│  │  /api/*     │  │  Hub        │  │  (propagate │  │               │  │
│  │             │  │  /ws/*      │  │  discoveries│  │  - users      │  │
│  │  - auth     │  │             │  │  preexisting│  │  - games      │  │
│  │  - games    │  │  - mod      │  │  links)     │  │    (JSONB     │  │
│  │  - users    │  │  - host     │  │             │  │    state)     │  │
│  │             │  │  - viewers  │  │             │  │               │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────────┘  │
│                                                                         │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ WSS
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│     Host      │         │   Viewer 1    │         │   Viewer N    │
│   (streamer)  │         │               │         │               │
│               │         │  Read-only    │         │  Read-only    │
│  - Dashboard  │         │  Same visual  │         │  Same visual  │
│  - Play view  │         │  state as     │         │  state as     │
│  - Edit pos.  │         │  host         │         │  host         │
└───────────────┘         └───────────────┘         └───────────────┘
```

## 2. Data Model

### 2.1 Database Schema (PostgreSQL)

Simplified schema with 2 tables. Game state (discoveries, positions, tags) is stored as JSONB
for simpler queries and fewer joins.

```sql
-- Users authenticated via Twitch
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    twitch_id TEXT UNIQUE NOT NULL,
    twitch_username TEXT NOT NULL,
    twitch_display_name TEXT,
    api_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

CREATE INDEX idx_users_twitch_username ON users(twitch_username);
CREATE INDEX idx_users_api_token ON users(api_token);

-- Game sessions (all state in JSONB columns)
CREATE TABLE games (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seed BIGINT NOT NULL,

    -- Identification
    run_id TEXT NOT NULL,  -- Unique ID from mod (save slot ID, character ID, or similar)
    label TEXT,            -- Display name (default: character name from mod, editable via dashboard)

    -- Full spoiler log data (needed for propagation logic)
    zone_pairs JSONB NOT NULL,  -- Array of {source, destination, type, source_details, target_details}

    -- State columns (JSONB)
    -- discovered_links: Array of {source, target, discovered_at, discovered_by}
    discovered_links JSONB NOT NULL DEFAULT '[]',
    -- node_positions: Dict of {node_id: {x, y}}
    node_positions JSONB NOT NULL DEFAULT '{}',
    -- tags: Dict of {zone_name: [tag1, tag2, ...]}
    tags JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL,  -- Soft delete

    UNIQUE(user_id, seed, run_id)
);

CREATE INDEX idx_games_user_id ON games(user_id);
CREATE INDEX idx_games_not_deleted ON games(user_id) WHERE deleted_at IS NULL;
```

**Why JSONB instead of separate tables:**
- Simpler queries (no joins needed)
- Atomic updates of game state
- All state fetched in one query
- Easier to reason about data model

### 2.2 Computed State

The server computes "discovered nodes" from the discovered_links JSONB column:

```python
def get_discovered_nodes(discovered_links: list[dict]) -> set[str]:
    """A node is discovered if it's in any discovered link, or is START_NODE."""
    discovered = {'Chapel of Anticipation'}

    for link in discovered_links:
        discovered.add(link['source'])
        discovered.add(link['target'])

    return discovered
```

### 2.3 Propagation Logic (Server-side)

When a discovery is received, the server propagates via preexisting links:

```python
async def propagate_discovery(db, game_id: UUID, source: str, target: str, discovered_by: str = "mod") -> list[dict]:
    """
    Propagate a discovery through preexisting links.
    Returns all newly discovered links (including the initial one).
    """
    game = await db.get(Game, game_id)
    zone_pairs = game.zone_pairs
    discovered_links = list(game.discovered_links or [])

    # Build adjacency for preexisting links only
    preexisting_adj = build_preexisting_adjacency(zone_pairs)

    # Get current discovered nodes
    discovered_nodes = get_discovered_nodes(discovered_links)

    # BFS through preexisting links
    newly_discovered = []
    queue = [(source, target)]
    visited = set()

    while queue:
        src, dst = queue.pop(0)
        if (src, dst) in visited:
            continue
        visited.add((src, dst))

        # Record this link as discovered (if not already)
        if not link_exists(discovered_links, src, dst):
            discovered_links.append({
                'source': src,
                'target': dst,
                'discovered_at': datetime.now(timezone.utc).isoformat(),
                'discovered_by': discovered_by,
            })
            newly_discovered.append({'source': src, 'target': dst})

        # If target was not previously discovered, propagate through preexisting
        if dst not in discovered_nodes:
            discovered_nodes.add(dst)
            for next_dst, _is_bidir in preexisting_adj.get(dst, []):
                if next_dst in discovered_nodes:
                    queue.append((dst, next_dst))

    # Update game with new discovered_links
    if newly_discovered:
        game.discovered_links = discovered_links
        await db.flush()

    return newly_discovered
```

## 3. REST API

### 3.1 Authentication

```
GET /auth/twitch
  → Redirect to Twitch OAuth

GET /auth/twitch/callback?code=xxx&state=xxx
  → Exchange code, create/get user
  → Redirect to /dashboard with session cookie or token

POST /auth/logout
  → Clear session
```

### 3.2 User Endpoints

```
GET /api/me
  → Returns current user info + API token
  Response: {
    "id": 123,
    "twitch_username": "streamername",
    "twitch_display_name": "StreamerName",
    "api_token": "xxx..."
  }

GET /api/users/{username}
  → Public user info (for /watch/:username)
  Response: {
    "username": "streamername",
    "display_name": "StreamerName"
  }

GET /api/users/{username}/games
  → Public list of user's games
  Response: {
    "games": [
      {"id": "uuid", "seed": 123, "label": "Malenia", "discovery_count": 45, "total_zones": 180, "updated_at": "..."}
    ]
  }
```

### 3.3 Game Endpoints

```
POST /api/games
  Auth: Bearer {api_token}  (from mod)
  Body: {
    "seed": 391139473,
    "run_id": "slot_0_char_12345",  // Unique ID from mod (save slot + character ID or similar)
    "label": "Radahn",              // Display name (character name), editable later
    "zone_pairs": [
      {"source": "Chapel of Anticipation", "destination": "Castle Ensis", "type": "random", "source_details": "...", "target_details": "..."},
      ...
    ]
  }
  Response: {"game_id": "uuid", "created": true}
  // or if game already exists:
  Response: {"game_id": "uuid", "created": false}

  Notes:
  - If game with same (user_id, seed, run_id) exists, returns existing game_id with created=false
  - zone_pairs includes BOTH random and preexisting links
  - Returns 429 if user already has MAX_GAMES_PER_USER games

GET /api/games/{game_id}
  → Full game state (public, for viewers)
  Response: {
    "id": "uuid",
    "seed": 391139473,
    "label": "Radahn",
    "zone_pairs": [...],
    "discovered_links": [
      {"source": "Chapel of Anticipation", "target": "Castle Ensis", "discovered_at": "..."}
    ],
    "discovered_nodes": ["Chapel of Anticipation", "Castle Ensis", ...],
    "node_positions": {"Chapel of Anticipation": {"x": 100, "y": 200}, ...},
    "tags": {"Castle Ensis": ["warning", "later"]},
    "created_at": "...",
    "updated_at": "..."
  }

GET /api/me/games
  Auth: Required (cookie or Bearer)
  → List of current user's games (excludes soft-deleted)
  Response: {
    "games": [
      {"id": "uuid", "seed": 123, "run_id": "slot_0_char_12345", "label": "Malenia", "discovery_count": 45, "total_zones": 180, "created_at": "...", "updated_at": "..."}
    ]
  }

DELETE /api/games/{game_id}
  Auth: Required (must be owner)
  → Soft delete a game (sets deleted_at, game no longer appears in lists)

PATCH /api/games/{game_id}
  Auth: Required (must be owner)
  Body: {"label": "New Name"}
  → Update game metadata (only label is editable)
```

### 3.4 Discovery Endpoint (REST fallback)

```
POST /api/games/{game_id}/discoveries
  Auth: Bearer {api_token}
  Body: {
    "source": "Chapel of Anticipation",
    "target": "Castle Ensis"
  }
  Response: {
    "propagated": [
      {"source": "Chapel of Anticipation", "target": "Castle Ensis"},
      {"source": "Castle Ensis", "target": "Some Preexisting Connection"}
    ]
  }

  Notes:
  - Server propagates through preexisting links
  - Returns all newly discovered links (for mod to know what happened)
```

## 4. WebSocket Protocol

### 4.1 Connection URLs

```
/ws/mod/{game_id}      # Mod connection (authenticated, can send discoveries)
/ws/host/{game_id}     # Host browser (authenticated, can send visual state)
/ws/viewer/{game_id}   # Viewer browser (read-only, receives visual state)
                       # Returns 429 if MAX_VIEWERS_PER_GAME reached
```

### 4.2 Authentication

Mod and Host must authenticate on connection:

```json
// Client → Server (first message after connect)
{"type": "auth", "token": "api_token"}

// Server → Client
{"type": "auth_ok"}
// or
{"type": "auth_error", "message": "Invalid token"}
```

Viewers don't need auth (game viewing is public).

### 4.3 Mod Messages

```json
// Mod → Server: Discovery event
{
  "type": "discovery",
  "source": "Chapel of Anticipation",
  "target": "Castle Ensis"
}

// Server → Mod: Discovery acknowledgment with propagation result
{
  "type": "discovery_ack",
  "propagated": [
    {"source": "Chapel of Anticipation", "target": "Castle Ensis"},
    {"source": "Castle Ensis", "target": "Preexisting Connection"}
  ]
}

// Mod → Server: Heartbeat
{"type": "ping"}

// Server → Mod: Heartbeat response
{"type": "pong"}
```

### 4.4 Host Messages

```json
// Host → Server: Full visual state update
{
  "type": "visual_state",
  "viewport": {"x": 0, "y": 0, "k": 1, "width": 1920, "height": 1080},
  "selected_node": "Castle Ensis",
  "frontier_highlight": true,
  "exploration_mode": true,
  "nodes": {
    "Chapel of Anticipation": {
      "x": 100, "y": 200,
      "highlighted": false, "dimmed": false,
      "frontier_highlight": false, "access_highlight": true
    },
    "???_Chapel of Anticipation_Castle Ensis": {
      "x": 150, "y": 220,
      "highlighted": true, "dimmed": false,
      "frontier_highlight": true, "access_highlight": false,
      "is_placeholder": true
    }
  },
  "links": {
    "Chapel of Anticipation->???_Chapel of Anticipation_Castle Ensis": {
      "highlighted": true, "dimmed": false, "frontier_highlight": true
    }
  }
}

// Host → Server: Node positions update (lighter, for drag events)
{
  "type": "positions_update",
  "positions": {
    "Chapel of Anticipation": {"x": 100, "y": 200},
    "Castle Ensis": {"x": 300, "y": 150}
  }
}

// Host → Server: Tag update
{
  "type": "tag_update",
  "zone": "Castle Ensis",
  "tags": ["warning", "later"]
}

// Host → Server: Manual discovery (clicked placeholder)
{
  "type": "manual_discovery",
  "source": "Chapel of Anticipation",
  "target": "Castle Ensis"
}
```

### 4.5 Server → All Clients (Broadcast)

```json
// Server → Host + Viewers: New discovery from mod
{
  "type": "discovery",
  "propagated": [
    {"source": "Chapel of Anticipation", "target": "Castle Ensis"}
  ]
}

// Server → Viewers: Visual state from host
{
  "type": "visual_state",
  // ... same as host sends
}

// Server → Viewers: Positions update from host
{
  "type": "positions_update",
  "positions": {...}
}

// Server → All: Tag update
{
  "type": "tag_update",
  "zone": "Castle Ensis",
  "tags": ["warning", "later"]
}

// Server → All: Heartbeat
{"type": "ping"}
```

### 4.6 Connection Lifecycle

```
1. Mod connects to /ws/mod/{game_id}
   - Sends auth
   - Receives auth_ok
   - Can now send discoveries

2. Host connects to /ws/host/{game_id}
   - Sends auth
   - Receives auth_ok
   - Receives current game state (discovered_links, positions, tags)
   - Starts sending visual_state updates

3. Viewer connects to /ws/viewer/{game_id}
   - No auth needed
   - Receives current visual_state immediately
   - Receives updates as host sends them

4. Mod sends discovery
   - Server propagates
   - Server broadcasts to host + viewers
   - Host updates local state and sends new visual_state
   - Viewers receive discovery + visual_state

5. Host disconnects
   - Viewers stay connected
   - Server keeps last visual_state
   - New viewers get last known state
   - When host reconnects, visual_state updates resume

6. Viewer reconnects
   - Gets current visual_state
   - Continues receiving updates
```

## 5. File Structure

```
server/
├── pyproject.toml           # Package config + dependencies
├── .env.example             # Environment template
├── fog-vizu.service         # Systemd unit file
├── fog-vizu.nginx.conf      # Nginx reverse proxy config
├── fogvizu/                  # Python module
│   ├── __init__.py
│   ├── main.py              # FastAPI app, route mounting
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # SQLAlchemy models + async session
│   ├── models.py            # Pydantic schemas (request/response)
│   ├── auth.py              # Twitch OAuth + token validation
│   ├── game_logic.py        # Propagation, one-way detection
│   ├── websocket.py         # WebSocket connection manager + handlers
│   └── api/
│       ├── __init__.py
│       ├── auth.py          # /auth/* routes
│       ├── users.py         # /api/users/* routes
│       └── games.py         # /api/games/* routes
├── alembic/                 # DB migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
└── venv/                    # Virtual environment (not committed)
```

## 6. Configuration

### 6.1 Environment Variables

See `server/.env.example` for the full template.

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/fogvizu

# Twitch OAuth
TWITCH_CLIENT_ID=xxx
TWITCH_CLIENT_SECRET=xxx
TWITCH_REDIRECT_URI=http://localhost:8001/auth/twitch/callback

# Server
SECRET_KEY=xxx  # For session signing
CORS_ORIGINS=["http://localhost:8001"]

# Limits (optional)
MAX_GAMES_PER_USER=10
MAX_VIEWERS_PER_GAME=100
HEARTBEAT_INTERVAL=30
```

### 6.2 Running the Server

```bash
cd server
source venv/bin/activate
uvicorn fogvizu.main:app --reload --port 8001
```

Or using the installed entry point:

```bash
fogvizu
```

## 7. Key Implementation Notes

### 7.1 One-Way Link Detection

```python
def is_one_way(link: dict, all_links: list[dict]) -> bool:
    """A link is one-way if no reverse link exists."""
    reverse_exists = any(
        l['source'] == link['destination'] and l['target'] == link['source']
        for l in all_links
    )
    return not reverse_exists
```

### 7.2 Visual State Persistence

Node positions are persisted to DB on every update (debounced). This ensures:
- Host can close browser and reopen with same layout
- Viewers see host's layout even if they join later

### 7.3 Placeholder Handling

Placeholders are NOT stored in DB. They are computed client-side based on:
- Discovered nodes/links
- Full zone_pairs data
- Current exploration mode

The host sends placeholder state in visual_state, viewers render them identically.

### 7.4 Race Condition: Mod vs Manual Discovery

If both mod and host try to discover the same link:
- Both call propagate_discovery()
- DB has UNIQUE constraint, duplicate inserts are ignored
- Both get back the propagation result
- No conflict, same end state

## 8. Migration from Current System

### 8.1 What Changes

| Component | Before | After |
|-----------|--------|-------|
| Session ID | 4-letter code | game UUID |
| State storage | In-memory (server.py) | PostgreSQL |
| Auth | None | Twitch OAuth |
| Discovery source | Manual clicks only | Mod + manual |
| Propagation | Client-side | Server-side |
| localStorage | Primary storage | Removed (or offline fallback) |

### 8.2 Frontend Changes Needed

1. Remove localStorage persistence (or keep for offline mode)
2. Add auth flow (login button, token storage)
3. Add dashboard page
4. Update sync.js to use new WebSocket protocol
5. Update exploration.js to handle server-driven discoveries
6. Add "backend abstraction" layer for offline mode

### 8.3 Backwards Compatibility

- Offline mode (`/?offline=true`) uses LocalBackend, works like before
- Old session URLs (`?viewer=true&session=ABCD`) → redirect to 404 or home
- New URLs: `/play/{gameId}`, `/watch/{username}/{gameId}`
