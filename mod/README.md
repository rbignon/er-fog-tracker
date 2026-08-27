# FogRandoTracker

In-game mod for Elden Ring that detects fog gate traversals and sends discoveries to the er-fog-tracker server for automatic visualization.

## Features

- Detects fog gate traversals, waygates, sending gates, and other teleports
- Sends discoveries to the server in real-time via WebSocket
- In-game overlay showing current zone and available exits
- Works with the Fog Gate Randomizer mod

## Building

**Requirements:**
- Rust toolchain (stable)
- Windows target (`x86_64-pc-windows-msvc`)

```bash
# Build DLL only
cargo build --release

# Build DLL + Launcher
cargo build --release --features launcher
```

**Outputs:**
- `target/release/fog_rando_tracker.dll` - The mod DLL
- `target/release/fog-rando-tracker-launcher.exe` - GUI launcher (with `--features launcher`)

**Supporting a new Elden Ring version:**

Game structure offsets come from `libeldenring`, pinned in `Cargo.toml` to a commit of the
[rbignon/eldenring-practice-tool](https://github.com/rbignon/eldenring-practice-tool) fork.
This mod still uses `hudhook` 0.7 / `windows` 0.54, so the pinned commit must come from a
`speedfog-vX.Y.Z-on-1.9.4` branch (version-support commits on top of upstream 1.9.4), not from
the `speedfog-vX.Y.Z` branches used by speedfog-racing (based on 1.9.5, which moved to `hudhook`
0.9 / `windows` 0.62). To bump: cherry-pick the fork's "Add support for Elden Ring X.Y.Z" commit
onto the latest `-on-1.9.4` branch, push it as `speedfog-vX.Y.Z-on-1.9.4`, update `rev` in
`Cargo.toml` and run `cargo update -p libeldenring -p macro-param`.

## Installation

1. Use the Launcher (recommended):
   - Run the launcher
   - Configure server URL and credentials
   - Click "Launch" to inject into Elden Ring

2. Manual injection:
   - Copy `fog_rando_tracker.dll` and `fog_rando_tracker.toml` to your preferred location
   - Use a DLL injector to inject into `eldenring.exe`

## Configuration

The mod reads configuration from `fog_rando_tracker.toml` (next to the DLL).

```toml
[keybindings]
toggle_ui = "f9"      # Show/hide overlay
toggle_debug = "f10"  # Show debug info
toggle_exits = "f11"  # Fold/unfold exits list

[overlay]
font_size = 16.0
background_opacity = 0.7

[logging]
console = false       # Enable debug console
log_file = ""         # Log file path (empty = disabled)
```

Server settings are managed by the Launcher and stored in `%APPDATA%/FogRandoTracker/launcher.toml`.

## Architecture

```
src/
├── core/           # Platform-independent logic (testable on Linux)
│   ├── animations.rs     # Animation IDs and teleport detection
│   ├── types.rs          # PlayerPosition, WarpInfo, etc.
│   ├── traits.rs         # GameStateReader, WarpDetector, SpEffectChecker
│   ├── constants.rs      # Entity ranges, memory offsets
│   ├── entity_utils.rs   # is_fog_rando_entity, get_teleport_type
│   ├── map_utils.rs      # format_map_id, parse_map_id
│   ├── warp_tracker.rs   # Warp detection state machine
│   ├── session.rs        # Server session management
│   ├── protocol.rs       # WebSocket protocol messages
│   ├── status_template.rs# Overlay text templates
│   └── color.rs          # Color parsing utilities
│
├── eldenring/      # Elden Ring memory reading (Windows-only)
│   ├── game_state.rs   # Player position, animation
│   ├── game_man.rs     # Warp detection via GameMan
│   ├── warp_hook.rs    # Memory hook for warp capture
│   ├── sp_effect.rs    # SpEffect reading
│   └── memory.rs       # Low-level memory access
│
├── dll/            # DLL mod implementation (Windows-only)
│   ├── tracker.rs      # Main tracker logic
│   ├── ui.rs           # ImGui overlay
│   ├── config.rs       # TOML configuration
│   ├── websocket.rs    # Server communication
│   ├── frame_state.rs  # Per-frame state management
│   ├── hotkey.rs       # Keyboard handling
│   ├── log_reader.rs   # Game log parsing
│   └── logging.rs      # Logging setup
│
├── launcher/       # GUI launcher (Windows-only, feature-gated)
│
└── lib.rs          # DLL entry point
```

## Testing

The `core/` module is platform-independent and can be tested on Linux:

```bash
# Run all tests (works on Linux)
cargo test

# Run with coverage
cargo test --lib -- --nocapture
```

Tests cover:
- Map ID formatting/parsing
- Entity ID classification
- Teleport animation detection
- Warp tracking state machine

## Fog Detection

The mod uses a **three-trigger detection strategy**:

1. **Animation trigger**: Detects known teleport animations (fog walls, waygates, etc.)
2. **FogRando trigger**: Detects warps via Fog Rando entity IDs (755890xxx), even with unknown animations
3. **Vanilla trigger**: Detects vanilla warps (coffins, scripted teleports) without distinctive animations

Common animations detected:

| Animation | Type |
|-----------|------|
| 60060 | Fog wall |
| 60460 | Back to entrance |
| 60490 | Waygate |
| 60470/60472 | Sending gate |
| 50340 | Pureblood Knight's Medal |

All discoveries are validated by checking that `warp_requested` was true during the warp, filtering false positives from cutscene animations.

For detailed documentation on memory structures, detection flow, and warp validation, see [docs/MOD_INTERNALS.md](../docs/MOD_INTERNALS.md).

## Server Integration

The mod connects to the er-fog-tracker server via WebSocket:

1. Log in to the fog-tracker website
2. Create a game from your spoiler log
3. Copy the mod token from the dashboard
4. Use the Launcher to configure and connect

The mod will:
- Auto-connect on game start
- Reconnect automatically if disconnected
- Show connection status in the overlay
- Display current zone and exits from the server

## License

AGPL-3.0 - See LICENSE file.

Uses code from [eldenring-practice-tool](https://github.com/veeenu/eldenring-practice-tool) by johndisandonato (AGPL-3.0).
