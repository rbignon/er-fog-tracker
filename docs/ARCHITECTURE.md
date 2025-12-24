# Fog Gate Randomizer Tracker - Architecture Overview

This document provides a high-level overview of the Fog Gate Randomizer Tracker project, explaining how all components work together.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ELDEN RING (Game)                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         Game Memory                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐   │   │
│  │  │ WorldChrMan  │  │   GameMan    │  │  FieldArea   │  │  ChrCtrl   │   │   │
│  │  │  (player)    │  │ (warp state) │  │ (play region)│  │ (animation)│   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                          │
│                                      │ Memory reads                             │
│                                      ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                     FogRandoTracker DLL (Rust)                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐   │   │
│  │  │  GameState   │  │   Tracker    │  │  WebSocket   │  │  Overlay   │   │   │
│  │  │   Reader     │──│  (events)    │──│   Client     │  │    UI      │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ WebSocket (wss://)
                                       │ discovery_v2 messages
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SERVER (Python FastAPI)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │   REST API   │  │  WebSocket   │  │    Zone      │  │     Database        │ │
│  │  /api/mod/*  │  │   Manager    │  │   Resolver   │  │   (PostgreSQL)      │ │
│  │  /api/games/*│  │ (rooms,sync) │  │  (matching)  │  │ games, users, links │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────────────┘ │
│         │                 │                 │                    │             │
│         └─────────────────┼─────────────────┼────────────────────┘             │
│                           │                 │                                   │
│                      ┌────┴────┐      ┌─────┴─────┐                            │
│                      │  Rooms  │      │ Data Files│                            │
│                      │mod,host,│      │ fog.txt   │                            │
│                      │ viewers │      │submaps.txt│                            │
│                      └─────────┘      └───────────┘                            │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ WebSocket (wss://) + HTTP
                                       │ visual_state, discovery sync
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           WEB UI (Vanilla JS + D3.js)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │    Graph     │  │  Exploration │  │     Sync     │  │       State        │  │
│  │  Renderer    │  │    Logic     │  │   (host/     │  │    Management      │  │
│  │   (D3.js)    │  │ (discovery)  │  │   viewer)    │  │   (pub/sub)        │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. In-Game Mod (Rust DLL)

**Purpose**: Detect fog gate traversals in real-time and report them to the server.

**Key responsibilities**:
- Read game memory to detect player position, animation state, and warp events
- Detect teleport animations: fog walls, waygates, sending gates, medals
- Send discovery events to server via WebSocket
- Display overlay UI showing current zone and available exits

**Technology**: Rust, hudhook (DirectX hooking), libeldenring (memory structures)

See: [MOD_INTERNALS.md](MOD_INTERNALS.md)

### 2. Launcher (Rust, Windows GUI)

**Purpose**: Configure the mod and create games on the server.

**Key responsibilities**:
- Validate randomizer folder structure (event/, spoiler_logs/)
- Parse spoiler log to extract seed and connections
- Parse EMEVD files to build entity mapping (improved zone resolution)
- Create game on server via REST API
- Generate mod configuration file

**Technology**: Rust, native-windows-gui

### 3. Server (Python FastAPI)

**Purpose**: Central hub for game state, authentication, and real-time sync.

**Key responsibilities**:
- Twitch OAuth authentication
- Store game data (zone pairs, discoveries, positions)
- Resolve zone names from map_id + position
- WebSocket rooms for host/viewer sync
- Broadcast discoveries to connected clients

**Technology**: Python, FastAPI, PostgreSQL, SQLAlchemy (async)

See: [PROTOCOL.md](PROTOCOL.md)

### 4. Web UI (Vanilla JS)

**Purpose**: Visualize the fog gate graph and exploration progress.

**Key responsibilities**:
- Render interactive graph using D3.js force simulation
- Exploration mode: progressive discovery with placeholders
- Streamer sync: host broadcasts state to viewers
- Manual discovery and node management

**Technology**: Vanilla JS (ES6 modules), D3.js, CSS

## Data Flow

### Game Creation Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Launcher │───▶│  Parse   │───▶│  Create  │───▶│  Server  │
│          │    │ Rando    │    │  Game    │    │  stores  │
│          │    │ Folder   │    │  (API)   │    │   game   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                     │
              ┌──────┴──────┐
              ▼             ▼
        ┌──────────┐  ┌──────────┐
        │ Spoiler  │  │  EMEVD   │
        │   Log    │  │  Files   │
        │(zone     │  │(entity   │
        │ pairs)   │  │ mapping) │
        └──────────┘  └──────────┘
```

1. User selects randomizer folder in launcher
2. Launcher validates folder structure
3. Launcher parses spoiler log → zone pairs
4. Launcher parses EMEVD files → entity mapping
5. Launcher sends both to server via POST /api/mod/games
6. Server stores game with enriched zone_pairs

### Discovery Flow (In-Game)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Player  │───▶│   Mod    │───▶│  Server  │───▶│  Web UI  │
│ traverses│    │ detects  │    │ resolves │    │ updates  │
│ fog gate │    │ & sends  │    │ & stores │    │  graph   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                     │               │
                     ▼               ▼
              ┌──────────┐    ┌──────────┐
              │discovery │    │  Zone    │
              │   _v2    │    │Resolver  │
              │ message  │    │(match to │
              │          │    │ spoiler) │
              └──────────┘    └──────────┘
```

1. Player walks through a fog gate
2. Mod detects teleport animation start → records entry position
3. Mod captures destination_entity_id from GameMan when available
4. Mod detects animation end + position readable → sends discovery_v2
5. Server resolves zone names using:
   - entity_mapping (if available)
   - Col-based matching
   - Position rules (submaps.txt)
   - Zone key matching (fog.txt)
6. Server stores discovered link and broadcasts to host/viewers
7. Web UI updates graph to show new discovery

### Streamer Sync Flow

```
┌──────────┐         ┌──────────┐         ┌──────────┐
│   Host   │◀───────▶│  Server  │◀───────▶│ Viewers  │
│ (browser)│  visual │  (room)  │  visual │(browsers)│
│          │  state  │          │  state  │          │
└──────────┘         └──────────┘         └──────────┘
      │                                         │
      │ Full control                Read-only   │
      │ - Select nodes                 mirror   │
      │ - Discover/undiscover                   │
      │ - Move nodes                            │
      │ - Change modes                          │
      └─────────────────────────────────────────┘
```

1. Host opens game in browser and connects via WebSocket
2. Viewers join with session code (read-only)
3. Host actions (selections, discoveries) are broadcast
4. Viewers receive and apply visual state updates
5. Node positions are persisted to server

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Mod | Rust | Memory reading, DLL injection |
| Mod | hudhook | DirectX overlay rendering |
| Mod | libeldenring | Game structure offsets |
| Launcher | Rust + native-windows-gui | Windows GUI application |
| Server | Python 3.11+ | Backend runtime |
| Server | FastAPI | REST API + WebSocket |
| Server | PostgreSQL | Persistent storage |
| Server | SQLAlchemy | Async ORM |
| Web | Vanilla JS (ES6) | No framework dependencies |
| Web | D3.js | Force-directed graph |

## Related Documentation

- [PROTOCOL.md](PROTOCOL.md) - API endpoints and WebSocket protocol
- [MOD_INTERNALS.md](MOD_INTERNALS.md) - Memory reading and event detection
- [GRAPH_MODEL.md](GRAPH_MODEL.md) - Zone pairs and link structure
- [ZONE_MATCHING.md](ZONE_MATCHING.md) - Zone resolution strategies
