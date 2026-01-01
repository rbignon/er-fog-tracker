# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

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
er-fog-tracker/
├── web/                    # Frontend (vanilla JS + D3.js)
│   ├── index.html
│   ├── js/                 # ES6 modules (state.js, graph.js, exploration.js, sync.js)
│   └── styles/
├── server/                 # Backend (Python FastAPI)
│   ├── fogtracker/         # Main module (api/, websocket.py, zone_resolver.py)
│   ├── tests/              # Pytest tests (unit/, integration/)
│   ├── alembic/            # Database migrations
│   └── data/               # Zone data files (fog.txt, submaps.txt)
├── mod/                    # In-game mod (Rust DLL + Launcher)
│   └── src/
│       ├── core/           # Platform-independent logic (testable on Linux)
│       ├── eldenring/      # Elden Ring memory reading (Windows-only)
│       ├── dll/            # DLL mod implementation (Windows-only)
│       ├── launcher/       # Windows GUI launcher
│       └── lib.rs          # DLL entry point (hudhook)
├── docs/                   # Architecture documentation
│   └── specs/              # Original design specs
├── analysis/               # CLI analysis scripts (not tests)
└── CONTRIBUTING.md         # Development and testing guide
```

## Running the Application

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # Configure environment
alembic upgrade head        # Run migrations
uvicorn fogtracker.main:app --reload --port 8001
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

### Mod Architecture (Rust)
The mod uses a layered architecture for testability:
- **core/**: Pure logic, no Windows dependencies, testable on Linux
- **eldenring/**: Memory reading via libeldenring (Windows-only)
- **dll/**: DLL entry point, UI, config (Windows-only)

Traits in `core/traits.rs` abstract the platform:
```rust
pub trait GameStateReader {
    fn read_position(&self) -> Option<PlayerPosition>;
    fn read_animation(&self) -> Option<u32>;
}
```

Implementations in `eldenring/` satisfy these traits. Tests in `core/` use mocks.

## Common Tasks

### Adding a new API endpoint
1. Add route in `server/fogtracker/api/`
2. Add models in `server/fogtracker/models.py`
3. Update `docs/PROTOCOL.md`

### Adding a new teleport type (mod)
1. Add constant in `mod/src/core/constants.rs`
2. Add case in `get_teleport_type()` in `mod/src/core/entity_utils.rs`
3. Add test in `mod/src/core/entity_utils.rs`
4. Update `docs/MOD_INTERNALS.md`

### Linting and Formatting

Pre-commit hooks handle linting and formatting:

```bash
pre-commit run --all-files          # Run all hooks manually
```

Hooks: `ruff` + `ruff-format` (Python), `eslint` + `prettier` (JS), `rustfmt` (Rust)

### Database migration

```bash
cd server
alembic revision -m "description"  # Create migration
alembic upgrade head               # Apply
alembic downgrade -1               # Rollback one migration
```

### Running tests

**Server (Python):**
```bash
cd server
pytest                                                    # Run unit tests
pytest tests/unit/test_zone_matching.py                   # Run specific file
pytest tests/unit/test_zone_matching.py::TestNamesMatch   # Run specific class
pytest tests/unit/test_zone_matching.py::TestNamesMatch::test_exact_match  # Specific test
pytest --cov=fogtracker tests/unit                        # With coverage
pytest --run-integration                                  # Integration tests (requires running server)
```

**Mod (Rust):**
```bash
cd mod
cargo test                          # Run all tests (works on Linux!)
cargo test --lib -- --nocapture     # With output
```

The mod's `core/` module is platform-independent - tests run on Linux without Windows dependencies.

### Fixing zone resolution issues

When a fog gate traversal fails to match (logs show "Zone non trouvée" or "No spoiler log match"):

1. **Capture baseline** before fixing:
   ```bash
   ./test_fog_resolution.py seeds/<seed_number>
   ```
   Note the "1 link" percentage and "not found" count.

2. **After fixing**, verify:
   - The specific case is now resolved
   - No regression: "1 link %" stays same or improves
   - No new "not found" cases introduced
   - All unit tests pass: `pytest tests/unit/`

3. **Add a unit test** in `tests/unit/test_zone_resolver.py` for the fix.

Key files for zone resolution:
- `server/fogtracker/zone_resolver.py` - Zone candidate resolution
- `server/fogtracker/zone_matching.py` - Spoiler log matching
- `server/fogtracker/websocket/mod.py` - Discovery handling
- `server/data/fog.txt` - Zone definitions and fog gates

## Deployment

See `server/README.md` for production deployment:
- Systemd service (`server/fog-tracker.service`)
- Nginx reverse proxy (`server/fog-tracker.nginx.conf`)
