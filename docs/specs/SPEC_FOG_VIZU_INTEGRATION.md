# Fog Visualizer Integration Specification

This document describes the integration between the Elden Ring Route Tracker mod and the er-fog-vizu web application for automatic zone discovery tracking.

> **Note:** This is the original design specification. Some sections have been superseded by actual implementation:
> - **Section 5 (Server Python Implementation)**: See `SPEC_BACKEND.md` for the actual implementation (FastAPI + PostgreSQL + SQLAlchemy, not aiohttp + SQLite)
> - **Section 7 (Communication Protocol)**: REST API is accurate; WebSocket protocol details in `SPEC_BACKEND.md`
> - Sections 1-4 (Overview, Architecture, Overlay, Mod) remain the reference design for future mod development.

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [User Experience & Overlay](#3-user-experience--overlay)
4. [Mod Rust Implementation](#4-mod-rust-implementation)
5. [Server Python Implementation](#5-server-python-implementation)
6. [Web Application Updates](#6-web-application-updates)
7. [Communication Protocol](#7-communication-protocol)
8. [Data Models](#8-data-models)
9. [Edge Cases & Error Handling](#9-edge-cases--error-handling)
10. [Security Considerations](#10-security-considerations)
11. [Implementation Phases](#11-implementation-phases)

---

## 1. Overview

### 1.1 Goal

Automate zone discovery tracking in er-fog-vizu when a player traverses fog gates in Elden Ring with the Fog Randomizer mod enabled.

### 1.2 Current State

- **Route Tracker Mod**: Detects fog gate traversals, captures `(map_id_src, map_id_dst)` and positions
- **er-fog-vizu**: Web app that visualizes fog randomizer connections, requires manual zone discovery

### 1.3 Target State

- Mod automatically resolves fog traversals to zone names
- Mod sends discoveries to server in real-time
- Web app updates graph automatically
- Viewers can watch streamer progress via public URL

### 1.4 Key Metrics

Based on analysis of two different seeds:
- **93-95%** of random transitions can be uniquely identified by map_ids
- **~3-4%** require user disambiguation (same-map transitions in legacy dungeons)
- **~3-4%** are ambiguous due to overlapping zone map_ids

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              PLAYER MACHINE                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐     reads      ┌─────────────────────────────────┐    │
│  │ Fog Rando   │ ◄───────────── │         Route Tracker Mod       │    │
│  │ Spoiler Log │                │                                 │    │
│  └─────────────┘                │  • Detects fog traversals       │    │
│                                 │  • Resolves map_ids → zones     │    │
│  ┌─────────────┐     reads      │  • Shows disambiguation UI      │    │
│  │  fog.txt    │ ◄───────────── │  • Sends discoveries to server  │    │
│  │ (zone defs) │                │                                 │    │
│  └─────────────┘                └──────────────┬──────────────────┘    │
│                                                │                        │
└────────────────────────────────────────────────┼────────────────────────┘
                                                 │ HTTPS/WSS
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                               SERVER                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        server.py                                 │   │
│  │                                                                  │   │
│  │  • REST API for auth & game management                          │   │
│  │  • WebSocket hub for real-time updates                          │   │
│  │  • SQLite database for persistence                              │   │
│  └──────────────────────────┬──────────────────────────────────────┘   │
│                             │                                           │
│  ┌──────────────────────────▼──────────────────────────────────────┐   │
│  │                      SQLite Database                             │   │
│  │                                                                  │   │
│  │  • Users (Twitch auth)                                          │   │
│  │  • Games (seed, zone_pairs, state)                              │   │
│  │  • Discoveries (per game)                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────┐
                    │                            │                        │
                    ▼                            ▼                        ▼
            ┌───────────────┐          ┌───────────────┐        ┌───────────────┐
            │   Player      │          │   Viewer 1    │        │   Viewer N    │
            │   Browser     │          │   Browser     │        │   Browser     │
            │               │          │               │        │               │
            │ /dashboard    │          │ /watch/:user/ │        │ /watch/:user/ │
            │               │          │   :gameId     │        │   :gameId     │
            └───────────────┘          └───────────────┘        └───────────────┘
```

### 2.2 Data Flow

```
1. SETUP PHASE
   ┌──────┐                    ┌────────┐                    ┌────────┐
   │Player│                    │ Server │                    │  Web   │
   └──┬───┘                    └───┬────┘                    └───┬────┘
      │                            │                             │
      │  Login with Twitch ───────►│                             │
      │◄────── API Token ─────────│                             │
      │                            │                             │
      │  Copy token to mod config  │                             │
      │                            │                             │

2. GAME START
   ┌──────┐                    ┌────────┐                    ┌────────┐
   │ Mod  │                    │ Server │                    │  Web   │
   └──┬───┘                    └───┬────┘                    └───┬────┘
      │                            │                             │
      │  POST /api/games           │                             │
      │  {token, seed, zone_pairs} │                             │
      │ ──────────────────────────►│                             │
      │                            │  Create game in DB          │
      │◄─────── {game_id} ────────│                             │
      │                            │                             │
      │  WS connect /ws/:game_id   │                             │
      │ ══════════════════════════►│                             │
      │                            │                             │
      │                            │◄───── WS connect ──────────│
      │                            │       (viewer mode)         │

3. FOG TRAVERSAL
   ┌──────┐                    ┌────────┐                    ┌────────┐
   │ Mod  │                    │ Server │                    │  Web   │
   └──┬───┘                    └───┬────┘                    └───┬────┘
      │                            │                             │
      │  Detect fog animation      │                             │
      │  Resolve map_ids → zones   │                             │
      │                            │                             │
      │  [If unique]               │                             │
      │  WS: discovery             │                             │
      │  {src, dst} ══════════════►│                             │
      │                            │  Store in DB                │
      │                            │  Broadcast ════════════════►│
      │                            │                             │  Update graph
      │                            │                             │
      │  [If ambiguous]            │                             │
      │  Show overlay UI           │                             │
      │  Player picks              │                             │
      │  WS: discovery ═══════════►│ ═══════════════════════════►│
```

---

## 3. User Experience & Overlay

### 3.1 Design Philosophy

The integration follows a **"smart remote control"** approach:
- **Overlay in-game**: Minimal but complete contextual info + quick actions
- **Website**: Full graph visualization, planning, viewer sync
- **Bidirectional sync**: Actions in overlay reflect on site and vice-versa

Most streamers have 2+ monitors, so the site remains open on a secondary screen.
The overlay reduces Alt-Tab for critical in-game decisions.

### 3.2 Overlay Views

#### 3.2.1 Contextual View (Default)

Shows information about the current zone and available exits.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  FARUM AZULA - DRAGON TEMPLE                          [⚠️][⏳][💰][✅] │
│  Scaling: tier 4, previously 14                                         │
│                                                                         │
│  EXITS (4)                                                              │
│  ──────────────────────────────────────────────────────────────────────│
│  [1] → Roundtable Hold                                                  │
│        From: dropping down                                              │
│                                                                         │
│  [2] → Farum Azula - Dragon Temple Transept                            │
│        From: completing the path atop floating debris                   │
│                                                                         │
│  [3] → ??? (undiscovered)                                              │
│        From: before back left of Godskin Duo arena, by the crumbled    │
│        stairs                                                           │
│                                                                         │
│  [4] → ??? (undiscovered)                                              │
│        From: at the front right of Godskin Duo arena                   │
│                                                                         │
│  ───────────────────────────────────────────────────────────────────── │
│  [1-4] Focus on map    [T] Add tag    [Tab] Global view    [H] Hide    │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key elements:**
- Zone name and scaling info
- Tag buttons (clickable or via T + number)
- All exits with full "From:" description from spoiler log
- ??? for undiscovered destinations
- Keyboard shortcuts for quick actions

#### 3.2.2 Global Frontier View (Toggle with Tab)

Shows ALL accessible undiscovered fogs across the entire game, grouped by source zone.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🌐 GLOBAL FRONTIER                                    12 fogs available │
│                                                                         │
│  FROM: Chapel of Anticipation                                           │
│  ──────────────────────────────────────────────────────────────────────│
│    [1] → Mt. Gelmir - Gelmir Hero's Grave                              │
│          before Grafted Scion's arena                                   │
│    [2] → Stormveil Castle after Gate                                   │
│          before Grafted Scion's arena                                   │
│                                                                         │
│  FROM: Farum Azula - Dragon Temple                                      │
│  ──────────────────────────────────────────────────────────────────────│
│    [3] → ??? (undiscovered)                                            │
│          before back left of Godskin Duo arena                         │
│    [4] → ??? (undiscovered)                                            │
│          at the front right of Godskin Duo arena                       │
│                                                                         │
│  FROM: Volcano Manor - Temple of Eiglay Shortcut Elevator              │
│  ──────────────────────────────────────────────────────────────────────│
│    [5] → Ancient Ruins of Rauh - Belfry Area                           │
│          after Godskin Noble's arena, down the shortcut elevator       │
│                                                                         │
│  ... (scrollable)                                                       │
│                                                                         │
│  ───────────────────────────────────────────────────────────────────── │
│  [↑↓] Navigate    [1-9] Focus on map    [Tab] Contextual view          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key elements:**
- Total count of accessible fogs
- Grouped by source zone (where player needs to go)
- Full "From:" details for navigation
- Scrollable for large frontier
- Number shortcuts to focus on map

### 3.3 Overlay Interactions

| Shortcut | Action | Effect on Site |
|----------|--------|----------------|
| `H` | Toggle overlay visibility | None |
| `Tab` | Switch contextual ↔ global view | None |
| `1-9` | Select fog by number | Focus + zoom on that node |
| `Enter` | Confirm selection | Focus + zoom on selected node |
| `↑↓` | Navigate list (global view) | Highlight node on map |
| `T` | Open tag menu | None |
| `T` + `1-6` | Quick tag (⚠️⏳💰✅⭐❌) | Tag appears on site |

### 3.4 Bidirectional Synchronization

```
┌─────────────────┐                              ┌─────────────────┐
│     OVERLAY     │                              │      SITE       │
│                 │                              │                 │
│  Select fog [3] │ ───── focus_node ─────────► │  Zoom to node   │
│                 │                              │  Highlight it   │
│                 │                              │                 │
│                 │ ◄──── camera_position ───── │  User pans/zoom │
│  (for viewer    │                              │                 │
│   sync info)    │                              │                 │
│                 │                              │                 │
│  Add tag ⚠️     │ ───── tag_added ──────────► │  Show tag on    │
│                 │                              │  node           │
│                 │                              │                 │
│                 │ ◄──── tag_added ─────────── │  User adds tag  │
│  Show tag       │                              │  via site       │
│                 │                              │                 │
│  Fog traversed  │ ───── discovery ──────────► │  Reveal node    │
│  (auto)         │                              │  Update graph   │
│                 │                              │                 │
│  Disambiguate   │ ───── discovery ──────────► │  Reveal node    │
│  choice         │                              │                 │
└─────────────────┘                              └─────────────────┘
```

### 3.5 Zone Detection for Contextual View

The overlay needs to know which zone the player is currently in to show relevant exits.

**Method:** Use the current `map_id` and match it against zone definitions.

```rust
// When player position is updated
let current_map_id = pointers.global_position.read_map_id();
let current_zone = zone_definitions.get_zone_for_map(current_map_id);

// Update overlay with exits from current_zone
let exits = zone_pairs.iter()
    .filter(|link| link.source == current_zone)
    .collect();
```

**Edge case:** Player might be in an area that spans multiple zones (overworld).
Use the most specific match based on map_id tile.

### 3.6 Viewer Experience

Viewers watching the stream see:
- The site in "viewer mode" (read-only)
- Real-time updates as streamer discovers zones
- Camera position synced with streamer's site view
- No access to overlay (it's on streamer's game screen)

Public URL: `https://er-fog-vizu.com/watch/{username}/{game_id}`

---

## 4. Mod Rust Implementation

### 4.1 New Files to Create

```
src/
├── fog_resolver.rs      # Zone resolution logic
├── zone_pairs.rs        # Zone pair data structures & parsing
├── server_client.rs     # HTTP + WebSocket client
├── disambiguation_ui.rs # Overlay UI for ambiguous cases
└── config updates to route_tracker.toml
```

### 4.2 fog_resolver.rs

Responsible for resolving `(map_id_src, map_id_dst)` to zone pair(s).

```rust
use std::collections::{HashMap, HashSet};

/// Result of attempting to resolve a fog traversal
pub enum ResolutionResult {
    /// Unique match found
    Unique(ZoneLink),
    /// Multiple possible matches - needs user disambiguation
    Ambiguous(Vec<ZoneLink>),
    /// Same map_id for src and dst - internal dungeon transition
    SameMap(Vec<ZoneLink>),
    /// No match found (unexpected)
    Unknown,
}

pub struct FogResolver {
    /// Map from (map_id_src, map_id_dst) -> list of possible zone links
    map_pair_to_links: HashMap<(String, String), Vec<ZoneLink>>,
    /// All zone pairs for this seed
    zone_pairs: Vec<ZoneLink>,
}

impl FogResolver {
    /// Create resolver from parsed spoiler log and fog.txt zone definitions
    pub fn new(zone_pairs: Vec<ZoneLink>, zone_definitions: &ZoneDefinitions) -> Self {
        let mut map_pair_to_links: HashMap<(String, String), Vec<ZoneLink>> = HashMap::new();

        for link in &zone_pairs {
            let src_maps = zone_definitions.get_maps(&link.source);
            let dst_maps = zone_definitions.get_maps(&link.destination);

            for src_map in src_maps {
                for dst_map in dst_maps {
                    map_pair_to_links
                        .entry((src_map.clone(), dst_map.clone()))
                        .or_default()
                        .push(link.clone());
                }
            }
        }

        Self { map_pair_to_links, zone_pairs }
    }

    /// Resolve a fog traversal to zone link(s)
    pub fn resolve(&self, map_id_src: &str, map_id_dst: &str) -> ResolutionResult {
        if map_id_src == map_id_dst {
            // Same-map transition (internal dungeon)
            if let Some(links) = self.map_pair_to_links.get(&(map_id_src.to_string(), map_id_dst.to_string())) {
                return ResolutionResult::SameMap(links.clone());
            }
            return ResolutionResult::Unknown;
        }

        match self.map_pair_to_links.get(&(map_id_src.to_string(), map_id_dst.to_string())) {
            Some(links) if links.len() == 1 => ResolutionResult::Unique(links[0].clone()),
            Some(links) => ResolutionResult::Ambiguous(links.clone()),
            None => ResolutionResult::Unknown,
        }
    }
}
```

### 4.3 zone_pairs.rs

Data structures and parsing for zone pairs.

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneLink {
    pub source: String,
    pub destination: String,
    pub connection_type: ConnectionType,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_details: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_details: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ConnectionType {
    Random,
    Preexisting,
}

#[derive(Debug)]
pub struct ZoneDefinitions {
    /// zone_name -> list of map_ids
    zone_to_maps: HashMap<String, Vec<String>>,
}

impl ZoneDefinitions {
    /// Parse fog.txt to extract zone -> map_id mappings
    pub fn from_fog_txt(content: &str) -> Result<Self, ParseError> {
        // Parse YAML-like fog.txt format
        // Extract "Name" and "Maps" fields from each Area
        todo!()
    }

    pub fn get_maps(&self, zone_name: &str) -> &[String] {
        self.zone_to_maps.get(zone_name).map(|v| v.as_slice()).unwrap_or(&[])
    }
}

/// Parse spoiler log to extract zone pairs
pub fn parse_spoiler_log(content: &str) -> Result<(u64, Vec<ZoneLink>), ParseError> {
    // Extract seed from first line
    // Parse "Random:" and "Preexisting:" lines
    // Return (seed, zone_pairs)
    todo!()
}
```

### 4.4 server_client.rs

HTTP and WebSocket client for server communication.

```rust
use tokio::sync::mpsc;

pub struct ServerClient {
    api_token: String,
    base_url: String,
    game_id: Option<String>,
    ws_sender: Option<mpsc::Sender<ServerMessage>>,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Start a new game session
    GameStart {
        seed: u64,
        zone_pairs: Vec<ZoneLink>,
    },
    /// Report a zone discovery
    Discovery {
        game_id: String,
        source: String,
        destination: String,
        connection_type: ConnectionType,
        timestamp_ms: u64,
    },
    /// Heartbeat to keep connection alive
    Ping,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerResponse {
    GameCreated { game_id: String },
    DiscoveryAck { success: bool },
    Error { message: String },
    Pong,
}

impl ServerClient {
    pub fn new(api_token: String, base_url: String) -> Self {
        Self {
            api_token,
            base_url,
            game_id: None,
            ws_sender: None,
        }
    }

    /// Start a new game and establish WebSocket connection
    pub async fn start_game(&mut self, seed: u64, zone_pairs: Vec<ZoneLink>) -> Result<String, Error> {
        // POST /api/games with auth header
        // Get game_id
        // Connect WebSocket to /ws/{game_id}
        // Store game_id and ws_sender
        todo!()
    }

    /// Send a discovery event
    pub async fn send_discovery(&self, source: &str, destination: &str, conn_type: ConnectionType) -> Result<(), Error> {
        // Send via WebSocket if connected, otherwise queue for later
        todo!()
    }
}
```

### 4.5 disambiguation_ui.rs

ImGui overlay for ambiguous zone resolution.

```rust
use imgui::Ui;

pub struct DisambiguationState {
    /// Currently pending disambiguation request
    pub pending: Option<DisambiguationRequest>,
    /// Callback to invoke when user makes choice
    pub on_resolved: Option<Box<dyn FnOnce(ZoneLink) + Send>>,
}

pub struct DisambiguationRequest {
    pub candidates: Vec<ZoneLink>,
    pub map_id_src: String,
    pub map_id_dst: String,
    pub timestamp: Instant,
}

impl DisambiguationState {
    pub fn render(&mut self, ui: &Ui) {
        if let Some(ref request) = self.pending {
            // Render modal window
            ui.window("Fog Gate Destination")
                .size([400.0, 200.0], imgui::Condition::FirstUseEver)
                .build(|| {
                    ui.text("Multiple destinations possible. Where did you go?");
                    ui.separator();

                    for (i, candidate) in request.candidates.iter().enumerate() {
                        let label = format!("{}. {} → {}",
                            i + 1,
                            candidate.source,
                            candidate.destination
                        );
                        if ui.button(&label) {
                            // User selected this candidate
                            if let Some(callback) = self.on_resolved.take() {
                                callback(candidate.clone());
                            }
                            self.pending = None;
                        }
                    }

                    ui.separator();
                    if ui.button("Skip (don't track)") {
                        self.pending = None;
                        self.on_resolved = None;
                    }
                });
        }
    }
}
```

### 4.6 Configuration Updates

Add to `route_tracker.toml`:

```toml
[server]
# API token from er-fog-vizu.com (get this after Twitch login)
api_token = ""

# Server URL (default: production server)
base_url = "https://er-fog-vizu.com"

# Enable/disable server sync
enabled = true

[fog_resolver]
# Path to fog.txt (auto-detected if not specified)
fog_txt_path = ""

# Path to fog randomizer spoiler logs directory (auto-detected if not specified)
spoiler_logs_dir = ""
```

### 4.7 Integration with Existing Tracker

Update `tracker.rs` to integrate fog resolution:

```rust
// In RouteTracker struct, add:
fog_resolver: Option<FogResolver>,
server_client: Option<ServerClient>,
disambiguation: DisambiguationState,

// In fog traversal detection (around line 260):
if let Some(pending) = self.pending_fog.take() {
    let exit_zone = get_zone_name(map_id);

    // Try to resolve the fog traversal
    if let Some(ref resolver) = self.fog_resolver {
        let entry_map = &pending.entry_map_id_str;
        let exit_map = WorldPositionTransformer::format_map_id(map_id);

        match resolver.resolve(entry_map, &exit_map) {
            ResolutionResult::Unique(link) => {
                // Send to server
                if let Some(ref client) = self.server_client {
                    client.send_discovery(&link.source, &link.destination, link.connection_type);
                }
            }
            ResolutionResult::Ambiguous(candidates) | ResolutionResult::SameMap(candidates) => {
                // Show disambiguation UI
                self.disambiguation.pending = Some(DisambiguationRequest {
                    candidates,
                    map_id_src: entry_map.clone(),
                    map_id_dst: exit_map,
                    timestamp: Instant::now(),
                });
            }
            ResolutionResult::Unknown => {
                warn!("Unknown fog traversal: {} -> {}", entry_map, exit_map);
            }
        }
    }

    // ... existing fog event recording ...
}
```

---

## 5. Server Python Implementation

> ⚠️ **SUPERSEDED**: This section describes an older design using aiohttp and SQLite.
> The actual implementation uses FastAPI + PostgreSQL + SQLAlchemy.
> See `SPEC_BACKEND.md` for current implementation details.

### 5.1 File Structure (Original Design)

```
er-fog-vizu/
├── server.py              # Main server (update existing)
├── database.py            # SQLite database layer (new)
├── models.py              # Data models (new)
├── auth.py                # Twitch OAuth (new)
└── requirements.txt       # Add new dependencies
```

### 5.2 Database Schema (SQLite)

```sql
-- Users authenticated via Twitch
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    twitch_id TEXT UNIQUE NOT NULL,
    twitch_username TEXT NOT NULL,
    twitch_display_name TEXT,
    api_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP
);

-- Game sessions (one per seed per user)
CREATE TABLE games (
    id TEXT PRIMARY KEY,  -- UUID
    user_id INTEGER NOT NULL REFERENCES users(id),
    seed INTEGER NOT NULL,
    zone_pairs_json TEXT NOT NULL,  -- JSON array of ZoneLink
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,

    UNIQUE(user_id, seed)  -- One game per seed per user
);

-- Individual zone discoveries
CREATE TABLE discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL REFERENCES games(id),
    source_zone TEXT NOT NULL,
    destination_zone TEXT NOT NULL,
    connection_type TEXT NOT NULL,  -- 'random' or 'preexisting'
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    client_timestamp_ms INTEGER,

    UNIQUE(game_id, source_zone, destination_zone)
);

-- User tags on zones (optional feature)
CREATE TABLE zone_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL REFERENCES games(id),
    zone_name TEXT NOT NULL,
    tag TEXT NOT NULL,  -- emoji tag
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(game_id, zone_name, tag)
);

-- Indexes
CREATE INDEX idx_games_user ON games(user_id);
CREATE INDEX idx_games_active ON games(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_discoveries_game ON discoveries(game_id);
```

### 5.3 database.py

```python
import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

class Database:
    def __init__(self, db_path: str = "fogvizu.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    # User methods
    def get_or_create_user(self, twitch_id: str, username: str, display_name: str) -> dict:
        """Get existing user or create new one with API token."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE twitch_id = ?",
                (twitch_id,)
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE users SET last_seen_at = ? WHERE id = ?",
                    (datetime.utcnow(), row['id'])
                )
                return dict(row)

            api_token = secrets.token_urlsafe(32)
            cursor = conn.execute(
                """INSERT INTO users (twitch_id, twitch_username, twitch_display_name, api_token)
                   VALUES (?, ?, ?, ?)""",
                (twitch_id, username, display_name, api_token)
            )
            return self.get_user_by_id(cursor.lastrowid)

    def get_user_by_token(self, api_token: str) -> Optional[dict]:
        """Authenticate user by API token."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE api_token = ?",
                (api_token,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get user by Twitch username (for public URLs)."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE twitch_username = ?",
                (username.lower(),)
            ).fetchone()
            return dict(row) if row else None

    # Game methods
    def create_game(self, user_id: int, seed: int, zone_pairs: list) -> str:
        """Create a new game or return existing one for this seed."""
        game_id = str(uuid.uuid4())
        with self.connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO games (id, user_id, seed, zone_pairs_json)
                       VALUES (?, ?, ?, ?)""",
                    (game_id, user_id, seed, json.dumps(zone_pairs))
                )
                return game_id
            except sqlite3.IntegrityError:
                # Game already exists for this user+seed
                row = conn.execute(
                    "SELECT id FROM games WHERE user_id = ? AND seed = ?",
                    (user_id, seed)
                ).fetchone()
                return row['id']

    def get_game(self, game_id: str) -> Optional[dict]:
        """Get game by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE id = ?",
                (game_id,)
            ).fetchone()
            if row:
                game = dict(row)
                game['zone_pairs'] = json.loads(game['zone_pairs_json'])
                return game
            return None

    def get_user_games(self, user_id: int) -> list:
        """Get all games for a user."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT id, seed, created_at, updated_at, is_active,
                          (SELECT COUNT(*) FROM discoveries WHERE game_id = games.id) as discovery_count
                   FROM games WHERE user_id = ? ORDER BY updated_at DESC""",
                (user_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # Discovery methods
    def add_discovery(self, game_id: str, source: str, destination: str,
                      connection_type: str, client_timestamp_ms: Optional[int] = None) -> bool:
        """Add a discovery. Returns True if new, False if already existed."""
        with self.connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO discoveries (game_id, source_zone, destination_zone,
                                                connection_type, client_timestamp_ms)
                       VALUES (?, ?, ?, ?, ?)""",
                    (game_id, source, destination, connection_type, client_timestamp_ms)
                )
                conn.execute(
                    "UPDATE games SET updated_at = ? WHERE id = ?",
                    (datetime.utcnow(), game_id)
                )
                return True
            except sqlite3.IntegrityError:
                return False  # Already discovered

    def get_discoveries(self, game_id: str) -> list:
        """Get all discoveries for a game."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT source_zone, destination_zone, connection_type,
                          discovered_at, client_timestamp_ms
                   FROM discoveries WHERE game_id = ? ORDER BY discovered_at""",
                (game_id,)
            ).fetchall()
            return [dict(row) for row in rows]
```

### 5.4 auth.py

```python
import os
import httpx
from dataclasses import dataclass
from typing import Optional

TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")
TWITCH_REDIRECT_URI = os.environ.get("TWITCH_REDIRECT_URI", "http://localhost:8000/auth/callback")

@dataclass
class TwitchUser:
    id: str
    login: str
    display_name: str

async def exchange_code_for_token(code: str) -> Optional[str]:
    """Exchange OAuth code for access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": TWITCH_REDIRECT_URI,
            }
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None

async def get_twitch_user(access_token: str) -> Optional[TwitchUser]:
    """Get Twitch user info from access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": TWITCH_CLIENT_ID,
            }
        )
        if resp.status_code == 200:
            data = resp.json()["data"][0]
            return TwitchUser(
                id=data["id"],
                login=data["login"],
                display_name=data["display_name"],
            )
        return None

def get_oauth_url(state: str) -> str:
    """Generate Twitch OAuth URL."""
    return (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={TWITCH_CLIENT_ID}"
        f"&redirect_uri={TWITCH_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=user:read:email"
        f"&state={state}"
    )
```

### 5.5 Updated server.py

```python
import asyncio
import json
import secrets
from typing import Dict, Set
from aiohttp import web, WSMsgType
from database import Database
from auth import exchange_code_for_token, get_twitch_user, get_oauth_url

db = Database()

# WebSocket connections per game_id
game_connections: Dict[str, Set[web.WebSocketResponse]] = {}

# ============================================================================
# REST API ROUTES
# ============================================================================

async def handle_auth_login(request: web.Request) -> web.Response:
    """Redirect to Twitch OAuth."""
    state = secrets.token_urlsafe(16)
    # Store state in session/cookie for verification
    response = web.HTTPFound(get_oauth_url(state))
    response.set_cookie("oauth_state", state, httponly=True, max_age=600)
    return response

async def handle_auth_callback(request: web.Request) -> web.Response:
    """Handle Twitch OAuth callback."""
    code = request.query.get("code")
    state = request.query.get("state")
    stored_state = request.cookies.get("oauth_state")

    if not code or state != stored_state:
        return web.HTTPBadRequest(text="Invalid OAuth state")

    access_token = await exchange_code_for_token(code)
    if not access_token:
        return web.HTTPBadRequest(text="Failed to get access token")

    twitch_user = await get_twitch_user(access_token)
    if not twitch_user:
        return web.HTTPBadRequest(text="Failed to get user info")

    user = db.get_or_create_user(twitch_user.id, twitch_user.login, twitch_user.display_name)

    # Redirect to dashboard with API token
    return web.HTTPFound(f"/dashboard?token={user['api_token']}")

async def handle_create_game(request: web.Request) -> web.Response:
    """Create a new game session."""
    # Authenticate
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.HTTPUnauthorized(text="Missing auth token")

    api_token = auth_header[7:]
    user = db.get_user_by_token(api_token)
    if not user:
        return web.HTTPUnauthorized(text="Invalid auth token")

    # Parse body
    try:
        data = await request.json()
        seed = data["seed"]
        zone_pairs = data["zone_pairs"]
    except (json.JSONDecodeError, KeyError) as e:
        return web.HTTPBadRequest(text=f"Invalid request body: {e}")

    # Create game
    game_id = db.create_game(user["id"], seed, zone_pairs)

    return web.json_response({"game_id": game_id})

async def handle_get_game(request: web.Request) -> web.Response:
    """Get game state (public, for viewers)."""
    game_id = request.match_info["game_id"]
    game = db.get_game(game_id)

    if not game:
        return web.HTTPNotFound(text="Game not found")

    discoveries = db.get_discoveries(game_id)

    return web.json_response({
        "game_id": game_id,
        "seed": game["seed"],
        "zone_pairs": game["zone_pairs"],
        "discoveries": discoveries,
    })

async def handle_get_user_games(request: web.Request) -> web.Response:
    """Get all games for authenticated user."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.HTTPUnauthorized()

    user = db.get_user_by_token(auth_header[7:])
    if not user:
        return web.HTTPUnauthorized()

    games = db.get_user_games(user["id"])
    return web.json_response({"games": games})

async def handle_get_user_public(request: web.Request) -> web.Response:
    """Get public user info by username (for /watch/:username)."""
    username = request.match_info["username"]
    user = db.get_user_by_username(username)

    if not user:
        return web.HTTPNotFound(text="User not found")

    games = db.get_user_games(user["id"])

    return web.json_response({
        "username": user["twitch_username"],
        "display_name": user["twitch_display_name"],
        "games": games,
    })

# ============================================================================
# WEBSOCKET HANDLER
# ============================================================================

async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket handler for real-time updates."""
    game_id = request.match_info.get("game_id")
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Track connection
    if game_id:
        if game_id not in game_connections:
            game_connections[game_id] = set()
        game_connections[game_id].add(ws)

    # Check if this is an authenticated mod connection
    is_mod = False
    user = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "auth":
                        # Mod authenticating
                        user = db.get_user_by_token(data.get("token", ""))
                        if user:
                            is_mod = True
                            await ws.send_json({"type": "auth_ok"})
                        else:
                            await ws.send_json({"type": "auth_error", "message": "Invalid token"})

                    elif msg_type == "discovery" and is_mod:
                        # Mod reporting a discovery
                        success = db.add_discovery(
                            game_id=data["game_id"],
                            source=data["source"],
                            destination=data["destination"],
                            connection_type=data["connection_type"],
                            client_timestamp_ms=data.get("timestamp_ms"),
                        )

                        # Broadcast to all viewers of this game
                        if success and data["game_id"] in game_connections:
                            broadcast_msg = json.dumps({
                                "type": "discovery",
                                "source": data["source"],
                                "destination": data["destination"],
                                "connection_type": data["connection_type"],
                            })
                            for viewer_ws in game_connections[data["game_id"]]:
                                if viewer_ws != ws:
                                    await viewer_ws.send_str(broadcast_msg)

                        await ws.send_json({"type": "discovery_ack", "success": success})

                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})

                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})

            elif msg.type == WSMsgType.ERROR:
                break

    finally:
        # Clean up connection
        if game_id and game_id in game_connections:
            game_connections[game_id].discard(ws)
            if not game_connections[game_id]:
                del game_connections[game_id]

    return ws

# ============================================================================
# APP SETUP
# ============================================================================

def create_app() -> web.Application:
    app = web.Application()

    # Auth routes
    app.router.add_get("/auth/login", handle_auth_login)
    app.router.add_get("/auth/callback", handle_auth_callback)

    # API routes
    app.router.add_post("/api/games", handle_create_game)
    app.router.add_get("/api/games/{game_id}", handle_get_game)
    app.router.add_get("/api/me/games", handle_get_user_games)
    app.router.add_get("/api/users/{username}", handle_get_user_public)

    # WebSocket
    app.router.add_get("/ws", handle_websocket)
    app.router.add_get("/ws/{game_id}", handle_websocket)

    # Static files (existing er-fog-vizu frontend)
    app.router.add_static("/", "src", show_index=True)

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
```

---

## 6. Web Application Updates

### 6.1 New Pages/Routes

| Route | Description |
|-------|-------------|
| `/` | Landing page (existing, add login button) |
| `/auth/login` | Redirect to Twitch OAuth |
| `/dashboard` | User's games list (authenticated) |
| `/play/:gameId` | Active game view (authenticated, full controls) |
| `/watch/:username` | Public user profile, list of games |
| `/watch/:username/:gameId` | Public game view (read-only) |

### 6.2 New JavaScript Modules

```
src/js/
├── api.js           # REST API client
├── auth.js          # Auth state management
├── dashboard.js     # Dashboard page logic
└── realtime.js      # WebSocket client for live updates
```

### 6.3 api.js

```javascript
const API_BASE = '';  // Same origin

export async function createGame(token, seed, zonePairs) {
    const resp = await fetch(`${API_BASE}/api/games`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ seed, zone_pairs: zonePairs }),
    });
    return resp.json();
}

export async function getGame(gameId) {
    const resp = await fetch(`${API_BASE}/api/games/${gameId}`);
    return resp.json();
}

export async function getMyGames(token) {
    const resp = await fetch(`${API_BASE}/api/me/games`, {
        headers: { 'Authorization': `Bearer ${token}` },
    });
    return resp.json();
}

export async function getUserPublic(username) {
    const resp = await fetch(`${API_BASE}/api/users/${username}`);
    return resp.json();
}
```

### 6.4 realtime.js

```javascript
export class RealtimeClient {
    constructor(gameId, onDiscovery) {
        this.gameId = gameId;
        this.onDiscovery = onDiscovery;
        this.ws = null;
        this.reconnectAttempts = 0;
    }

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}/ws/${this.gameId}`);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'discovery') {
                this.onDiscovery(data.source, data.destination, data.connection_type);
            }
        };

        this.ws.onclose = () => {
            // Reconnect with exponential backoff
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            this.reconnectAttempts++;
            setTimeout(() => this.connect(), delay);
        };

        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
        };
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}
```

### 6.5 Integration with Existing exploration.js

```javascript
// In exploration.js, add method to handle server-driven discovery:

export function discoverFromServer(sourceZone, destZone, connectionType) {
    // Find the link in graph data
    const link = State.graphData.links.find(l =>
        getNodeId(l.source) === sourceZone &&
        getNodeId(l.target) === destZone
    );

    if (link) {
        // Use existing discovery logic
        discoverArea(destZone, sourceZone, link);
    }
}
```

---

## 7. Communication Protocol

### 7.1 REST API

#### Authentication

```
GET /auth/login
  → Redirect to Twitch OAuth

GET /auth/callback?code=xxx&state=xxx
  → Exchange code, create/get user, redirect to /dashboard?token=xxx
```

#### Games

```
POST /api/games
  Headers: Authorization: Bearer <api_token>
  Body: {
    "seed": 391139473,
    "zone_pairs": [
      {"source": "Chapel of Anticipation", "destination": "Castle Ensis", "connection_type": "random"},
      ...
    ]
  }
  Response: {"game_id": "uuid"}

GET /api/games/:game_id
  Response: {
    "game_id": "uuid",
    "seed": 391139473,
    "zone_pairs": [...],
    "discoveries": [
      {"source_zone": "...", "destination_zone": "...", "connection_type": "...", "discovered_at": "..."},
      ...
    ]
  }

GET /api/me/games
  Headers: Authorization: Bearer <api_token>
  Response: {
    "games": [
      {"id": "uuid", "seed": 391139473, "discovery_count": 5, "created_at": "...", "updated_at": "..."},
      ...
    ]
  }

GET /api/users/:username
  Response: {
    "username": "streamername",
    "display_name": "StreamerName",
    "games": [...]
  }
```

### 7.2 WebSocket Protocol

#### Connection

```
ws://server/ws/:game_id
```

#### Messages (Client → Server)

```json
// Authenticate (mod only)
{"type": "auth", "token": "api_token"}

// Report discovery (mod only, after auth)
{
  "type": "discovery",
  "game_id": "uuid",
  "source": "Chapel of Anticipation",
  "destination": "Castle Ensis",
  "connection_type": "random",
  "timestamp_ms": 12345
}

// Add tag to a zone (from mod or site)
{
  "type": "tag_add",
  "game_id": "uuid",
  "zone": "Farum Azula - Dragon Temple",
  "tag": "⚠️"
}

// Remove tag from a zone (from mod or site)
{
  "type": "tag_remove",
  "game_id": "uuid",
  "zone": "Farum Azula - Dragon Temple",
  "tag": "⚠️"
}

// Focus on a node (from mod, to sync with site)
{
  "type": "focus_node",
  "game_id": "uuid",
  "zone": "Farum Azula - Dragon Temple"
}

// Camera position update (from site, for viewer sync)
{
  "type": "camera_position",
  "game_id": "uuid",
  "x": 123.45,
  "y": 678.90,
  "zoom": 1.5
}

// Keepalive
{"type": "ping"}
```

#### Messages (Server → Client)

```json
// Auth response
{"type": "auth_ok"}
{"type": "auth_error", "message": "Invalid token"}

// Discovery acknowledgment (to mod)
{"type": "discovery_ack", "success": true}

// Discovery broadcast (to all viewers and site)
{
  "type": "discovery",
  "source": "Chapel of Anticipation",
  "destination": "Castle Ensis",
  "connection_type": "random"
}

// Tag broadcast (to all clients - mod, site, viewers)
{
  "type": "tag_added",
  "zone": "Farum Azula - Dragon Temple",
  "tag": "⚠️"
}

{
  "type": "tag_removed",
  "zone": "Farum Azula - Dragon Temple",
  "tag": "⚠️"
}

// Focus broadcast (to site and viewers when mod requests focus)
{
  "type": "focus_node",
  "zone": "Farum Azula - Dragon Temple"
}

// Camera position broadcast (to viewers for sync)
{
  "type": "camera_position",
  "x": 123.45,
  "y": 678.90,
  "zoom": 1.5
}

// Keepalive response
{"type": "pong"}

// Error
{"type": "error", "message": "..."}
```

---

## 8. Data Models

### 8.1 Zone Link (shared between mod and server)

```json
{
  "source": "Chapel of Anticipation",
  "destination": "Castle Ensis",
  "connection_type": "random",
  "source_details": "(before Grafted Scion's arena)",
  "target_details": "(on the bridge from Gravesite Plain)"
}
```

### 8.2 Game State

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 123,
  "seed": 391139473,
  "zone_pairs": [ /* array of ZoneLink */ ],
  "discoveries": [
    {
      "source_zone": "Chapel of Anticipation",
      "destination_zone": "Castle Ensis",
      "connection_type": "random",
      "discovered_at": "2024-01-15T10:30:00Z",
      "client_timestamp_ms": 12345
    }
  ],
  "tags": {
    "Farum Azula - Dragon Temple": ["⚠️", "⏳"],
    "Volcano Manor": ["💰"]
  },
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### 8.3 Available Tags

| Tag | Emoji | Meaning |
|-----|-------|---------|
| Warning | ⚠️ | Dangerous area, be careful |
| Later | ⏳ | Come back later |
| Loot | 💰 | Good items to get |
| Done | ✅ | Completed this area |
| Star | ⭐ | Important/favorite |
| Blocked | ❌ | Can't progress here |
| Key | 🔑 | Need key item |

### 8.4 User

```json
{
  "id": 123,
  "twitch_id": "12345678",
  "twitch_username": "streamername",
  "twitch_display_name": "StreamerName",
  "api_token": "xxx...xxx",
  "created_at": "2024-01-01T00:00:00Z"
}
```

---

## 9. Edge Cases & Error Handling

### 9.1 Mod Edge Cases

| Case | Handling |
|------|----------|
| No spoiler log found | Show error in UI, disable sync |
| Multiple spoiler logs | Use most recent, or let user pick |
| Invalid API token | Show error, prompt to reconfigure |
| Server unreachable | Queue discoveries locally, retry |
| WebSocket disconnect | Auto-reconnect with backoff |
| Disambiguation timeout | Auto-skip after 30s, log as unknown |
| Game already exists for seed | Reuse existing game, continue |

### 9.2 Server Edge Cases

| Case | Handling |
|------|----------|
| Duplicate discovery | Ignore (UNIQUE constraint), return success |
| Invalid game_id | Return 404 |
| Invalid token | Return 401 |
| Rate limiting | 100 requests/min per token |
| Large zone_pairs payload | Max 1MB, return 413 if exceeded |

### 9.3 Web App Edge Cases

| Case | Handling |
|------|----------|
| Game not found | Show "Game not found" page |
| User not found | Show "User not found" page |
| WebSocket disconnect | Show "Reconnecting..." indicator |
| Stale data | Re-fetch on reconnect |

---

## 10. Security Considerations

### 10.1 Authentication

- API tokens are random 256-bit values (secrets.token_urlsafe(32))
- Tokens stored hashed in database (optional, adds complexity)
- Twitch OAuth for initial authentication
- No password storage

### 10.2 Authorization

- API token required for write operations
- Game viewing is public (by design, for viewers)
- Users can only modify their own games

### 10.3 Input Validation

- Validate seed is integer
- Validate zone_pairs structure
- Sanitize zone names (no HTML/script injection)
- Rate limit API requests

### 10.4 Privacy

- Twitch username is public (linked to streaming anyway)
- API token should never be displayed on stream
- Store token in config file, not environment variable

---

## 11. Implementation Phases

### Phase 1: Mod Foundation (Rust)
**Estimated scope: Core parsing and resolution**

- [ ] Implement `zone_pairs.rs` - parse spoiler log
- [ ] Implement zone definitions parsing from fog.txt
- [ ] Implement `fog_resolver.rs` - map_id to zone resolution
- [ ] Unit tests for resolution accuracy
- [ ] Integration with existing fog detection

### Phase 2: Server Backend (Python)
**Estimated scope: API and persistence**

- [ ] Set up SQLite database with schema
- [ ] Implement `database.py`
- [ ] Implement Twitch OAuth flow
- [ ] REST API endpoints
- [ ] WebSocket handler
- [ ] Basic rate limiting

### Phase 3: Mod Server Communication (Rust)
**Estimated scope: Network client**

- [ ] HTTP client for game creation
- [ ] WebSocket client for real-time updates
- [ ] Offline queue for unreachable server
- [ ] Configuration for server URL and token

### Phase 4: Overlay UI (Rust)
**Estimated scope: Full ImGui overlay with contextual and global views**

- [ ] Contextual view (current zone + exits)
- [ ] Global frontier view (all accessible fogs)
- [ ] Zone detection from map_id
- [ ] Keyboard navigation (1-9, arrows, Tab, T)
- [ ] Tag management UI
- [ ] Disambiguation popup for ambiguous transitions
- [ ] Focus node → site sync

### Phase 5: Web App Updates (JavaScript)
**Estimated scope: Dashboard, live view, and bidirectional sync**

- [ ] Auth flow integration (Twitch OAuth)
- [ ] Dashboard page (list of games)
- [ ] Real-time updates via WebSocket (discoveries, tags)
- [ ] Focus sync from mod → site (zoom to node)
- [ ] Camera position sync for viewers
- [ ] Public watch pages (/watch/:username/:gameId)
- [ ] Mobile-friendly viewer mode

### Phase 6: Bidirectional Tag Sync
**Estimated scope: Tags work from both mod and site**

- [ ] Tag add/remove from site → mod sync
- [ ] Tag add/remove from mod → site sync
- [ ] Tags persistence in database
- [ ] Tags display in overlay

### Phase 7: Polish & Testing
**Estimated scope: Hardening**

- [ ] End-to-end testing (mod → server → site → viewer)
- [ ] Error handling improvements
- [ ] Offline mode (queue when server unreachable)
- [ ] Performance optimization
- [ ] Documentation

---

## Appendix A: File Locations

### Fog Randomizer Files (Windows)

```
# Typical installation paths
C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game\randomizer\
├── fog.txt                           # Zone definitions
└── spoiler_logs\
    └── YYYY-MM-DD_HH.MM.SS_log_SEED_XXXXX.txt
```

### Mod Configuration

```
# Next to DLL
route_tracker.toml
```

---

## Appendix B: Zone Resolution Analysis Results

From analysis of two seeds:

| Metric | Seed 391139473 | Seed 126601463 |
|--------|----------------|----------------|
| Total random transitions | 181 | 163 |
| Fully identifiable | 91.2% | 94.5% |
| Partially ambiguous | 2.2% | 0.6% |
| Fully ambiguous | 3.3% | 4.3% |
| Same-map (internal) | 3.3% | 0.6% |
| **Effective rate** | **93.4%** | **95.1%** |

Common problematic zones:
- Volcano Manor (internal transitions)
- Ashen Leyndell / Erdtree Sanctuary
- Farum Azula
- Nokron / Academy of Raya Lucaria
