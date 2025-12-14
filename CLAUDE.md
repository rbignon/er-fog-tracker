# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Elden Ring Fog Gate Randomizer Tracker - a web-based tool to visualize and track exploration progress for the Fog Gate Randomizer mod. Includes an optional in-game mod for automatic discovery tracking. Frontend with Python WebSocket backend for streamer sync and mod integration.

## Project Structure

```
er-fog-vizu/
├── web/                    # Frontend (vanilla JS + D3.js)
│   ├── index.html
│   ├── js/                 # ES6 modules
│   └── styles/
├── server/                 # Backend (Python FastAPI)
│   ├── pyproject.toml
│   ├── fogvizu/            # Python module
│   │   ├── main.py
│   │   ├── api/
│   │   └── ...
│   ├── alembic/            # DB migrations
│   └── README.md           # Server setup instructions
├── mod/                    # In-game mod (Rust DLL)
│   ├── src/
│   └── README.md
├── tests/                  # Integration tests
└── docs/                   # Design specifications
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

Open `http://localhost:8001` in browser. See `server/README.md` for detailed instructions.

## Architecture

**State Management** (`web/js/state.js`):
- Centralized state with pub/sub event bus
- `State.subscribe('eventName', callback)` for inter-module communication
- Setters emit events automatically (e.g., `setExplorationMode()` emits `explorationModeChanged`)

**Module Structure**:
- `main.js` - Entry point, orchestration
- `state.js` - Single source of truth + event bus
- `parser.js` - Spoiler log parsing (SpoilerLogParser, ItemLogParser)
- `graph.js` - D3.js force simulation, rendering, interactions
- `ui.js` - File upload, controls, search, modals
- `exploration.js` - Discovery logic, pathfinding, preexisting propagation
- `sync.js` - WebSocket streamer sync (host/viewer modes)

**Backend** (`server/fogvizu/`):
- FastAPI with REST API and WebSocket support
- PostgreSQL database with SQLAlchemy ORM (async)
- Twitch OAuth authentication
- Serves static files from `web/`

**Data Flow**: File Upload → Parser → State → Graph Render → UI Events → State Updates → WebSocket Sync

## Key Patterns

**Graph Data**:
- Nodes: `{ id, isBoss, scaling, isHub }`
- Links: `{ source, target, type: 'random'|'preexisting', oneWay, requiredItemFrom }`

**Exploration State**:
- `discovered`: Set of area IDs
- `discoveredLinks`: Set of link IDs (format: `"sourceId|targetId"`)
- `tags`: Map of area ID → array of tag IDs
- Preexisting connections auto-propagate discoveries

**WebSocket Sync**:
- Host creates session via `/ws/host`, receives 4-char code
- Viewers join via `/ws/viewer/{code}`
- Visual state (CSS classes, positions, viewport) synced in real-time
- Viewer mode: `?viewer=true&session=CODE`
- Classes synced: `highlighted`, `dimmed`, `frontier-highlight`, `access-highlight`

## Important Conventions

- Events that modify DOM visuals should delay `syncState()` by ~50ms to capture CSS changes
- Viewer never recalculates highlights locally - applies classes received from host
- localStorage persists exploration per seed: `er-fog-exploration-{seed}`
- D3 selections use `.node` and `.link` classes

## Known Pitfalls (WebSocket Sync)

1. **Sync timing**: Events like `nodeSelected`, `frontierHighlightChanged` must wait ~50ms before sync so CSS classes are applied to DOM first

2. **CSS classes to sync**: `highlighted`, `dimmed`, `frontier-highlight`, `access-highlight` - all must be captured in `getFullSyncState()` and applied in `applyVisualClasses()`

3. **Exploration mode**: Must be synced (`explorationMode` in state) otherwise viewer keeps old mode when host changes

4. **No recalculation on viewer**: Viewer applies received classes directly. It must never call `highlightFrontier()` itself - check `State.isStreamerHost()` before any local calculation

## Exploration Mode Logic

### Design Goal: Zero Spoilers

The exploration mode simulates blind exploration of a randomized game. **The user must never be spoiled about what lies behind unexplored connections.**

Key principles:
- **Placeholders (???) reveal nothing**: A placeholder shows "there's something here" but never hints at what's behind it - whether it leads to a new area or loops back to an already-discovered location
- **No visual distinction**: Placeholders for undiscovered nodes look identical to placeholders for undiscovered links to known nodes. The user cannot tell if clicking a placeholder will reveal a new area or connect to somewhere they've already been
- **Surprise is preserved**: When the user clicks a placeholder, they discover what's behind it - this mirrors the in-game experience of walking through a fog gate without knowing the destination

This is why link discovery tracking exists: even if both endpoints of a link are discovered, the link itself stays hidden (shown as placeholder) until explicitly traversed.

### Highlight Modes

**Without node selected:**
- Frontier mode OFF: Display entire graph normally
- Frontier mode ON: Highlight placeholder nodes (???) with `frontier-highlight`, discovered nodes adjacent to undiscovered with `access-highlight`, dim everything else

**With node selected (Frontier mode is suspended):**
- "Path from Start" ON: Highlight shortest path from Chapel of Anticipation to selected node + direct neighbors of selected node, dim everything else
- "Path from Start" OFF: Follow "subway line" behavior - highlight connected nodes until reaching hubs (nodes with 3+ connections), dim everything else
- In exploration mode, both modes stop at undiscovered nodes boundary (don't traverse placeholders)

### Discovery/Undiscovery

**When discovering a node:**
- Recursively discover all connected nodes via preexisting links (respecting one-way)
- Select the newly discovered node
- Preserve node positions during re-render

**When undiscovering a node:**
- Cannot undiscover START_NODE (Chapel of Anticipation)
- Cascade: also undiscover all nodes that become unreachable from START_NODE
- Clear selection (don't try to select a placeholder - ambiguous if multiple exist)
- Reachability check respects one-way links

### Placeholder Nodes (???)

Placeholders represent unexplored connections. They are created in two cases:
1. **Undiscovered node**: Adjacent to a discovered node (classic case)
2. **Undiscovered link**: Between two discovered nodes where the link hasn't been traversed yet

- ID format: `???_{sourceNodeId}_{realNodeId}`
- One-way links: placeholder created only in traversable direction
- Positioned near their source node with deterministic offset (hash-based)
- `isUndiscoveredLink: true` flag marks placeholders for links between discovered nodes

### Link Discovery

Links between nodes must be explicitly discovered (traversed) to become visible:
- When discovering a node via a placeholder, only the specific link used is discovered
- Other links to/from the newly discovered node remain hidden until traversed
- Bidirectional links: discovering one direction discovers both
- Legacy saves (without `discoveredLinks`) are auto-migrated: all links between discovered nodes marked as discovered

### One-Way Links

Computed in `computeOneWayLinks()`: a link is one-way if no reverse link exists.
- Discovery propagation: can follow forward, blocked backward on one-way
- Undiscovery reachability: same rules
- Path finding: same rules
- Placeholder creation: only in traversable direction

## Deployment

See `server/README.md` for production deployment instructions including:
- Systemd service configuration (`server/fog-vizu.service`)
- Nginx reverse proxy (`server/fog-vizu.nginx.conf`)
- Environment configuration
