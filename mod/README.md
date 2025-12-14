# FogRandoTracker - Elden Ring Fog Gate Randomizer Tracker

DLL mod for Elden Ring that detects fog gate traversals and integrates with er-fog-vizu for automatic zone discovery visualization.

## Building

**Requirements:**
- Rust toolchain with Windows target
- Windows (or cross-compilation setup)

```bash
# Build release DLL
cargo build --release

# Outputs:
# - target/release/fog_rando_tracker.dll (the mod)
# - target/release/fog-rando-tracker-injector.exe (standalone injector)
```

## Installation

1. Copy `fog_rando_tracker.toml` next to the DLL (required - configuration file)
2. Inject the DLL into Elden Ring using the injector or a mod loader.

## Configuration

Edit `fog_rando_tracker.toml` to configure:
- Hotkey for UI toggle (default: F9)
- Server integration for fog-vizu

## Architecture

| File | Purpose |
|------|---------|
| `lib.rs` | DLL entry point, hudhook/ImGui initialization |
| `tracker.rs` | Core logic: fog traversal detection |
| `game_state.rs` | Game state reading (position, map_id, animation) |
| `ui.rs` | ImGui overlay rendering |
| `config.rs` | TOML config parsing |
| `hotkey.rs` | Keyboard shortcut handling |
| `websocket.rs` | WebSocket client for server integration |
| `injector.rs` | Standalone DLL injector |

## Fog Detection

Fog gate traversal is detected via animation ID 60060. The tracker captures:
1. Entry position + map_id when animation starts
2. Exit position + map_id when animation ends

The server matches coordinates to zone names using the game's map data.

## Integration with er-fog-vizu

The mod connects to the er-fog-vizu server via WebSocket to automatically send fog gate discoveries in real-time.

### Setup

1. Log in to the fog-vizu website with your Twitch account
2. Create a new game from your spoiler log
3. Copy your mod token and game ID from the dashboard
4. Edit `fog_rando_tracker.toml` and fill in the `[server]` section:

```toml
[server]
enabled = true
url = "wss://fogvizu.malenia.win"
mod_token = "your-mod-token-here"
game_id = "your-game-uuid-here"
auto_reconnect = true
```

### Features

- Automatic discovery sync when traversing fog gates
- Connection status shown in the UI overlay
- Auto-reconnect with exponential backoff
- Works even if you start playing before the website is ready
