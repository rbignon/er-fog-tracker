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

The mod uses **animation-based detection** for all known teleport types. This is more reliable than checking `warp_requested` or entity ID ranges because:
- The `destination_entity_id` in GameMan may not be the Fog Rando entity ID (the game uses its own entity IDs for some warps)
- Animation detection catches all fog gates regardless of how the game internally handles the warp

### Supported Teleport Types

| Type | Animation ID | Notes |
|------|-------------|-------|
| Fog Wall | `60060` | Most common |
| Waygate | `60490` | Sending gates to other areas |
| Sending Gate (Blue) | `60470` | Portal-style gates |
| Sending Gate (Red) | `60472` | Portal-style gates |
| Medal | `50340` | Pureblood Knight's Medal item use |
| Horned Remains | `60010` | Teleport to Regal Ancestor Spirit (Nokron) |
| Liurnia Tower Door | `12202126` | Opening the door at the bottom of the inverted tower. **Requires validation** (see below) |
| Post Boss Warp | `12020210` | Warp after defeating a boss (e.g., Maliketh). **Requires validation** (see below) |
| Erdtree Burn | `68110` | Cutscene warp when burning the Erdtree with Melina |

### Detection Flow

```
┌──────────────────────────────────────────────────────────────┐
│                        Timeline                              │
├──────────────────────────────────────────────────────────────┤
│  t=0      t=1s         t=1.5s        t=2s        t=2.5s     │
│   │        │            │             │            │         │
│   ▼        ▼            ▼             ▼            ▼         │
│ Player  Animation   dest_entity   Loading     Position       │
│ enters   starts     captured      screen      readable       │
│ fog                 from GameMan  (pos=None)  (exit pos)     │
│                                                              │
│ ─────▶ ENTRY ─────▶ CAPTURE ─────────────────▶ EXIT ─────▶  │
│        (store       (poll until                (send         │
│        entry pos)   non-zero)                  discovery)    │
└──────────────────────────────────────────────────────────────┘
```

1. **Entry Detection**: When a teleport animation starts (`get_teleport_type(anim_id)` returns Some), record the entry position
2. **Entity Capture**: Poll `GameMan.destination_entity_id` each frame until non-zero
3. **Exit Detection**: When animation ends AND position is readable, send discovery

### Coffin Transport

Coffins have no distinctive animation and are currently not explicitly detected. If Fog Rando randomizes coffin destinations, the warp would be classified as "OTHER" transport type.

### Fast Travel

Fast travel (via map menu) is **not tracked** by the mod. It uses `warp_requested` without a teleport animation, but since it's not a fog gate traversal, it's intentionally ignored.

### Cutscene Animation Validation

Some animations in the `12xxxxxx` range (`POST_BOSS_WARP`, `LIURNIA_TOWER_DOOR`) can be triggered without an actual warp occurring (e.g., during cutscenes or visual transitions). To filter these false positives, discoveries with these transport types are validated before being sent to the server.

A discovery with these animation types is considered **valid** only if `warp_requested` was true at some point during the warp. The tracker monitors `GameMan.warp_requested` each frame while a warp is pending and records if it ever becomes true.

**Example false positive** (filtered):
```
Animation: LIURNIA_TOWER_DOOR (12202126)
Entry: m43_01_00_00 (-90.1, 357.2, 22.1)
Exit:  m43_01_00_00 (-71.6, 347.8, 16.9)
warp_requested: never true
→ Discarded (no warp was actually requested by the game)
```

Other teleport types (FOG, WAYGATE, MEDAL, etc.) are always valid because their animations are only played during actual warps.

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

## Pending Warp State Machine

A single `PendingWarp` struct tracks the current teleport:

```rust
struct PendingWarp {
    entry: PlayerPosition,       // Position when animation started
    destination_entity_id: u32,  // Captured from GameMan (may be 0 initially)
    transport_type: &'static str, // "FOG", "WAYGATE", "SENDING_GATE", "MEDAL", or "OTHER"
}
```

State transitions:

```
                            ┌─────────────────────────┐
                            │     IDLE                │
                            │ (pending_warp = None)   │
                            └───────────┬─────────────┘
                                        │
                        Teleport animation starts
                        (was_in_teleport_anim: false → true)
                                        │
                                        ▼
                            ┌─────────────────────────┐
              Entry pos     │     PENDING             │
              captured      │ (pending_warp = Some)   │
                            │ dest_entity polled each │
                            │ frame until non-zero    │
                            └───────────┬─────────────┘
                                        │
                    Animation ends + position readable
                    (was_in_teleport_anim: true → false)
                                        │
                                        ▼
                            ┌─────────────────────────┐
                            │     EXIT                │
                            │ Send discovery_v2       │
                            │ Clear pending_warp      │
                            └─────────────────────────┘
```

**Delayed exit handling**: If the animation ends while position is still unreadable (loading screen), the pending warp is kept and the discovery is sent on the next frame when position becomes readable.

## Entity IDs in FogMod

FogMod uses entity IDs in range `755890000-755899999` for its spawn points. Each fog gate transition involves two entity IDs:

### Destination Entity (dest_entity)

The spawn point on the **destination side** of the fog gate. This is the entity ID used by the `WarpPlayer` instruction (2003:14) to teleport the player.

- **Captured from**: `GameMan.initial_area_entity_id` when `warp_requested` becomes true
- **Used for**: Zone resolution (map lookup via entity_mapping)

### Source Entity (source_entity)

The spawn point on the **source side** of the fog gate. This is the entity ID used by the `RotateCharacter` instruction (2004:14) to orient the player after teleportation, making them face back toward where they came from.

- **Extracted from**: EMEVD files during launcher parsing
- **Purpose**: The game uses this to know what direction the player was facing when entering the fog
- **Relation to dest_entity**: For bidirectional fog gates, `source_entity` from map A is the `dest_entity` when warping FROM map A, while `dest_entity` from map A is the `source_entity` when warping TO map A

```
        Map A                           Map B
    ┌───────────┐                   ┌───────────┐
    │           │                   │           │
    │  source_  │    fog gate       │  dest_    │
    │  entity   │◄─────────────────►│  entity   │
    │  (orient  │                   │  (warp    │
    │   point)  │                   │   point)  │
    │           │                   │           │
    └───────────┘                   └───────────┘

    When warping A→B:
    - WarpPlayer uses dest_entity (in Map B)
    - RotateCharacter uses source_entity (in Map A) to orient player

    The reverse warp B→A would use the opposite entities.
```

## Destination Entity Capture

The destination entity ID is polled each frame while a warp is pending:

```rust
// Capture dest_entity_id when available (happens after animation start for fog gates)
if let Some(ref mut pending) = self.pending_warp {
    if pending.destination_entity_id == 0 {
        let dest_entity_id = self.game_man_reader.get_destination_entity_id();
        if dest_entity_id != 0 {
            pending.destination_entity_id = dest_entity_id;
        }
    }
}
```

This polling approach is necessary because:
1. The `WarpPlayer` instruction (which sets the entity ID) executes ~1 second AFTER the fog animation starts
2. For some warp types (e.g., sending gates), the entity ID in GameMan may not be the Fog Rando entity ID at the exact moment `warp_requested` becomes true

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
2. Clear zone info when exiting a loading screen (but **not** if a warp is pending, to avoid clearing info received from the server during the warp)

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

The mod uses `tracing` for structured logging. Output can be configured in `fog_rando_tracker.toml`:

```toml
[logging]
console = true          # Show debug console window
log_file = "mod.log"    # Write to file (optional)
```

Log prefixes:
- `[WARP]`: Teleport events (animation start, entity capture, complete)
- `[ANIM]`: Animation changes (with known IDs labeled)
- `[SPEFFECT]`: Active SpEffect list changes
- `[GAMEMAN]`: Warp state changes
- `[WS TX]`, `[WS RX]`: WebSocket traffic
