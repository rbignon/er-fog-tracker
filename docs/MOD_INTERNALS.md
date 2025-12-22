# Mod Internals

This document describes how the in-game mod reads Elden Ring memory and detects fog gate traversals.

## Architecture

The mod is a Rust DLL injected into the Elden Ring process using DirectX hooking (hudhook).

```
┌─────────────────────────────────────────────────────────────┐
│                    FogRandoTracker DLL                      │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  GameState  │  │  SpEffect   │  │     GameMan         │ │
│  │   Reader    │  │   Reader    │  │      Reader         │ │
│  │             │  │             │  │                     │ │
│  │ - position  │  │ - effects   │  │ - warp_requested    │ │
│  │ - map_id    │  │ - item use  │  │ - dest_entity_id    │ │
│  │ - animation │  │             │  │ - dest_map_id       │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         └────────────────┼─────────────────────┘            │
│                          ▼                                  │
│                   ┌─────────────┐                          │
│                   │   Tracker   │                          │
│                   │  (per-frame │                          │
│                   │   polling)  │                          │
│                   └──────┬──────┘                          │
│                          │                                  │
│         ┌────────────────┼────────────────┐                │
│         ▼                ▼                ▼                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  WebSocket  │  │   Overlay   │  │   Config    │        │
│  │   Client    │  │     UI      │  │   (TOML)    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## Memory Structures

The mod reads several game structures via pointer chains. Base addresses are resolved by `libeldenring`.

### WorldChrMan (Player Character)

Primary structure for player state.

```
WorldChrMan (base address)
    └─[0x1E508] PlayerIns (player instance, offset varies by version)
          ├─[0x178] SpEffectCtrl (active effects)
          ├─[0x160] tae_queued_use_item (item being used)
          └─ ChrCtrl
               └─ cur_anim (current animation ID)
```

**Version-specific offsets**:
- V1.02.0 - V1.06.0: `PlayerIns` at offset `0x18468`
- V1.07.0+: `PlayerIns` at offset `0x1E508`

### GameMan (Game State)

Global game state including warp information.

```
GameMan (base address)
    ├─[0x10]  warp_requested (bool) - true when warp is pending
    ├─[0x3C]  initial_area_entity_id (u32) - destination entity ID
    └─[0xAC8] load_target_block_id (u32) - destination map ID
```

### FieldArea (Play Region)

Contains the current play region ID (used for Col-based zone resolution).

```
FieldArea (base address)
    └─[0xE4] play_region_id (u32)
```

### Global Position

Player's world position and current map.

```
GlobalPosition
    ├─ x, y, z (f32) - world coordinates
    └─ map_id (u32) - encoded as 0xWWXXYYDD
```

**Map ID Format**: `mWW_XX_YY_DD`
- WW = world number (10 = Limgrave, 11 = Liurnia, etc.)
- XX = area within world
- YY = sub-area
- DD = detail level

## Teleport Detection

The mod detects different types of teleportation:

### Fog Wall Traversal

**Detection method**: Animation-based

1. **Entry**: Animation ID `60060` starts
2. **During**: `warp_requested` becomes true (capture `destination_entity_id`)
3. **Exit**: Animation ends AND position is readable

```
┌──────────────────────────────────────────────────────────────┐
│                        Timeline                              │
├──────────────────────────────────────────────────────────────┤
│  t=0      t=1s         t=1.5s        t=2s        t=2.5s     │
│   │        │            │             │            │         │
│   ▼        ▼            ▼             ▼            ▼         │
│ Player  Animation   WarpPlayer   Loading     Position       │
│ enters   60060      executes     screen      readable       │
│ fog      starts     (sets        (pos=None)  (exit pos)     │
│                     dest_id)                                 │
│                                                              │
│ ─────▶ ENTRY ─────▶ CAPTURE ─────────────────▶ EXIT ─────▶  │
│        (store       (update                    (send         │
│        entry pos)   dest_entity)               discovery)    │
└──────────────────────────────────────────────────────────────┘
```

### Waygate / Sending Gate

**Detection method**: Animation-based

- **Animation ID**: `60490`
- Flow same as fog wall

### Coffin Transport

**Detection method**: Exclusion-based + SpEffect verification

Coffins have no distinctive animation. Detection uses:

1. **Primary (exclusion)**: `warp_requested` = true AND no fog/waygate/medal animation AND `destination_entity_id` = 0
2. **Secondary (SpEffect)**: Active SpEffect IDs: `4190`, `4010`, or `4510`

```rust
let is_coffin = (warp_requested && no_animation && dest_entity_id == 0)
             || has_coffin_speffect;
```

### Pureblood Knight's Medal

**Detection method**: Animation + Item ID

1. **Animation**: `50340` (item use animation)
2. **Item check**: `tae_queued_use_item` == `0x40000870` (Medal item ID)

Both conditions must be true to avoid false positives from other item uses.

### Fast Travel

**Detection method**: GameMan state

- `warp_requested` = true
- `destination_entity_id` != 0 (grace entity ID)
- No animation-based event active

Fast travel is detected but not sent as a discovery (it's not a fog gate).

## SpEffect Reading

SpEffects are stored in a linked list on the player character:

```
SpEffectCtrl
    └─[0x8] first_node
              ├─[0x8] sp_effect_id (u32)
              └─[0x30] next_node
```

The mod iterates through the list (max 256 nodes) to find specific effect IDs.

**Notable SpEffect IDs**:
- `4280`: Teleportation effect (debug display)
- `4190`, `4010`, `4510`: Coffin transport effects
- `106`: Grace spawn effect (after fast travel/death)

## Pending Event State Machine

Each teleport type has its own pending event state:

```rust
struct PendingEvent {
    entry: PlayerPosition,       // Position when event started
    destination_entity_id: u32,  // FogMod spawn point (755890xxx)
}
```

State transitions per teleport type:

```
                            ┌─────────────────────────┐
                            │     IDLE                │
                            │ (pending = None)        │
                            └───────────┬─────────────┘
                                        │
                        Animation/SpEffect detected
                                        │
                                        ▼
                            ┌─────────────────────────┐
              Entry pos     │     PENDING             │
              captured      │ (pending = Some)        │
                            │ dest_entity = 0 or      │
                            │ captured on warp_req    │
                            └───────────┬─────────────┘
                                        │
                    Animation ends + position readable
                                        │
                                        ▼
                            ┌─────────────────────────┐
                            │     EXIT                │
                            │ Send discovery_v2      │
                            │ Clear pending          │
                            └─────────────────────────┘
```

## Destination Entity Capture

FogMod uses entity IDs in range `755890000-755899999` for warp destinations.

The entity ID is captured when `warp_requested` transitions from false to true:

```rust
if warp_requested && !self.was_warp_requested {
    let dest_id = self.game_man_reader.get_destination_entity_id();

    // Update any pending events that haven't captured yet
    if let Some(ref mut pending) = self.pending_fog {
        if pending.destination_entity_id == 0 && dest_id != 0 {
            pending.destination_entity_id = dest_id;
        }
    }
    // ... same for waygate, medal, coffin
}
```

This is necessary because `WarpPlayer` instruction (which sets the entity ID) executes ~1 second AFTER the fog animation starts.

## Discovery Message

When a traversal completes, the mod sends:

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

The `destination_entity_id` is the key for entity mapping lookup on the server.

## Loading Screen Handling

During loading screens:
- Position is unreadable (returns `None`)
- Map ID is `0xFFFFFFFF`

The mod tracks `was_position_readable` to:
1. Wait for exit position before sending discovery
2. Clear zone info when exiting a loading screen

## Overlay UI

The mod displays an ImGui overlay showing:
- Current zone name (from server)
- Available exits (with ??? for undiscovered destinations)
- Discovery progress (X/Y zones)
- Connection status

The overlay is rendered via DirectX hook (hudhook library).

## Configuration

The mod reads `fogrando_tracker.toml` from the DLL directory:

```toml
[server]
enabled = true
url = "https://fog.example.com"
mod_token = "your-token-here"
game_id = "uuid-of-game"
auto_reconnect = true

[keybindings]
toggle_ui = "F8"

[overlay]
font_path = "segoeui.ttf"
font_size = 16.0
```

## Debug Logging

The mod logs to stdout (visible in console when launched with console):
- `[FOG]`, `[WAYGATE]`, `[MEDAL]`, `[COFFIN]`: Teleport events
- `[ANIM]`: Animation changes (with known IDs labeled)
- `[SPEFFECT]`: Active SpEffect list changes
- `[GAMEMAN]`: Warp state changes
- `[WS TX]`, `[WS RX]`: WebSocket traffic
