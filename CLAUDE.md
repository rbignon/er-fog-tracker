# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Elden Ring Fog Gate Randomizer Tracker - a web-based tool to visualize and track exploration progress for the Fog Gate Randomizer mod. Includes an optional in-game mod for automatic discovery tracking.

**For detailed architecture documentation, see `docs/`:**
- `docs/ARCHITECTURE.md` - System overview, components, data flows
- `docs/PROTOCOL.md` - REST API and WebSocket protocol
- `docs/MOD_INTERNALS.md` - Memory reading and warp detection
- `docs/GRAPH_MODEL.md` - Zone links, discovery logic
- `docs/ZONE_MATCHING.md` - Zone resolution strategies

## Project Structure

```
er-fog-vizu/
├── web/                    # Frontend (vanilla JS + D3.js)
│   ├── index.html
│   ├── js/                 # ES6 modules (state.js, graph.js, exploration.js, sync.js)
│   └── styles/
├── server/                 # Backend (Python FastAPI)
│   ├── fogvizu/            # Main module (api/, websocket.py, zone_resolver.py)
│   ├── alembic/            # Database migrations
│   └── data/               # Zone data files (fog.txt, submaps.txt)
├── mod/                    # In-game mod (Rust DLL + Launcher)
│   └── src/
│       ├── lib.rs          # DLL entry point (hudhook)
│       ├── tracker.rs      # Warp detection logic
│       ├── game_state.rs   # Memory reading
│       ├── websocket.rs    # Server communication
│       └── launcher/       # Windows GUI launcher
├── docs/                   # Architecture documentation
│   └── specs/              # Original design specs
└── tests/
```

## Running the Application

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # Configure environment
alembic upgrade head        # Run migrations
uvicorn fogvizu.main:app --reload --port 8001
```

Open `http://localhost:8001` in browser.

## Key Concepts

### Roles
- **Mod**: In-game DLL, sends discoveries via WebSocket
- **Host**: Streamer's browser, full control, broadcasts to viewers
- **Viewer**: Read-only browser, mirrors host's visual state

### Graph Model
- **Zone**: Node in the graph (area in Elden Ring)
- **Zone Link**: Link between zones (fog gate connection)
- **Types**: `random` (randomized) vs `preexisting` (vanilla connection)
- **One-way**: Some links can only be traversed in one direction

### Exploration Mode
- Undiscovered connections shown as `???` placeholders
- Links must be explicitly traversed to become visible
- Preexisting connections auto-propagate discoveries
- Zero spoilers: placeholders reveal nothing about destination

### Zone Matching
The mod sends `(map_id, position, destination_entity_id)`, server resolves to zone names:
1. Col-based lookup (play_region_id) - most precise
2. Entity mapping (from EMEVD parsing) - improves precision
3. Position rules (submaps.txt) - fallback
4. Display name matching - last resort

## Important Patterns

### State Management (Frontend)
```javascript
State.subscribe('eventName', callback);  // Pub/sub
State.setSelectedNodeId(id);             // Setter emits event
State.isExplorationMode();               // Getter
```

### WebSocket Sync
- Host actions broadcast to viewers via server
- Viewers apply received state, never recalculate locally
- CSS classes synced: `highlighted`, `dimmed`, `frontier-highlight`, `access-highlight`

### Discovery Propagation
```
Discover Zone B via link A→B
  → Mark link A→B as discovered
  → If B has preexisting links to C, D...
    → Recursively discover C, D (respecting one-way)
```

### Undiscovery Cascade
```
Undiscover Zone B
  → Find all zones reachable from START via discovered links
  → Undiscover any zones not in reachable set
```

## Common Tasks

### Adding a new API endpoint
1. Add route in `server/fogvizu/api/`
2. Add models in `server/fogvizu/models.py`
3. Update `docs/PROTOCOL.md`

### Adding a new teleport type (mod)
1. Add variant to `TeleportType` enum in `game_state.rs`
2. Add detection logic in `tracker.rs`
3. Update `docs/MOD_INTERNALS.md`

### Database migration
```bash
cd server
alembic revision -m "description"  # Create migration
alembic upgrade head               # Apply
```

## Deployment

See `server/README.md` for production deployment:
- Systemd service (`server/fog-vizu.service`)
- Nginx reverse proxy (`server/fog-vizu.nginx.conf`)
