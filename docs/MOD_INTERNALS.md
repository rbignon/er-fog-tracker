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
│                   ┌─────────────┐     ┌─────────────┐      │
│                   │   Tracker   │◄────│  Warp Hook  │      │
│                   │  (per-frame │     │ (lua_warp)  │      │
│                   │   polling)  │     │ grace_id    │      │
│                   └──────┬──────┘     └─────────────┘      │
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
    ├─[0x3C]  initial_area_entity_id (u32) - spawn point entity ID (fog rando: 755890xxx)
    └─[0xAC8] load_target_block_id (u32) - destination map ID
```

**Note**: The offset `0xB3C` was previously documented as `target_grace` but returns 0 in practice. The mod now uses a function hook to capture the grace entity ID (see Warp Hook section below).

**Entity ID usage**:
- `initial_area_entity_id` (0x3C): Spawn point entity ID, used for fog gate tracking
- Grace entity ID: Captured via warp hook, used for fast travel zone resolution

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

The mod uses a **three-trigger detection strategy**:

1. **Trigger A (Animation)**: Detects known teleport animations (fog walls, waygates, etc.)
2. **Trigger B (FogRando)**: Detects when `warp_requested` becomes true with a Fog Rando entity ID (755890000-755899999), even if the animation is unknown
3. **Trigger C (VanillaWarp)**: Detects vanilla warps (coffins, scripted teleports) when `warp_requested` becomes true with:
   - `dest_entity_id != 0` (not death/respawn/reminiscence)
   - `target_grace == 0` (not fast travel)
   - Entity not in Fog Rando range (not already handled by Trigger B)

This approach ensures we catch:
- All standard fog gate traversals (via animation detection)
- Fog gates with unknown/new animations (via entity ID detection)
- Vanilla warps like coffins (e.g., after Valiant Gargoyles) that have no distinctive animation

**Trigger Priority**: Triggers are evaluated in order A → B → C. The first to match wins. This ensures known animations get their specific transport type, Fog Rando warps are labeled "FOG_RANDO", and unknown vanilla warps get "VANILLA_WARP".

**Validation**: ALL discoveries require `warp_requested` to have been true at some point during the warp. This filters false positives like cutscene animations that play without an actual warp occurring.

### Supported Teleport Types

| Type | Animation ID | Trigger | Notes |
|------|-------------|---------|-------|
| Fog Wall | `60060` | A | Most common |
| Back to Entrance | `60460` | A | Ground teleporter after defeating dungeon boss |
| Waygate | `60490` | A | Sending gates to other areas |
| Sending Gate (Blue) | `60470` | A | Portal-style gates |
| Sending Gate (Red) | `60472` | A | Portal-style gates |
| Medal | `50340` | A | Pureblood Knight's Medal item use |
| Horned Remains | `60010` | A | Teleport to Regal Ancestor Spirit (Nokron) |
| Liurnia Tower Door | `12202126` | A | Opening the door at the bottom of the inverted tower |
| Post Boss Warp | `12020210` | A | Warp after defeating a boss (e.g., Maliketh) |
| Erdtree Burn | `68110` | A | Cutscene warp when burning the Erdtree with Melina |
| Placidusax Lie Down | `67010` | A | Lie down animation to access Placidusax boss arena |
| FOG_RANDO | (any) | B | Entity-triggered detection for unknown animations (755890xxx) |
| VANILLA_WARP | (any) | C | Vanilla warps with no known animation (coffins, scripted) |

### Warp Timeline (Player Perspective)

A typical fog gate traversal from the player's perspective:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Timeline                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  t=0        t=0.5s       t=1s          t=1.5s       t=2s         t=2.5s     │
│   │           │           │              │           │             │         │
│   ▼           ▼           ▼              ▼           ▼             ▼         │
│ Player    Animation   warp_requested  Loading    Position      Discovery    │
│ enters     starts      becomes true   screen     readable       sent        │
│ fog gate              dest_entity     (pos=None) (exit pos)                 │
│                       captured                                              │
│                                                                              │
│ ──────▶ ENTRY ──────▶ CAPTURE ──────────────────▶ EXIT ──────▶ SEND ──────▶ │
│         (record       (poll each                  (create       (if valid)  │
│         entry pos)    frame)                      discovery)                │
└──────────────────────────────────────────────────────────────────────────────┘
```

This timing explains why:
- We poll `dest_entity_id` each frame (it's set ~0.5-1s after animation starts)
- We track `warp_was_requested` (it becomes true during the warp, not at the start)
- We wait for position to be readable (loading screen can last 1-2s)

### Detection Flow

The complete warp detection workflow:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         WARP DETECTION WORKFLOW                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

                           ┌─────────────────────────┐
                           │   MEMORY READING        │
                           │      (each frame)       │
                           └───────────┬─────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
┌───────────────┐           ┌─────────────────────┐         ┌────────────────┐
│ PlayerIns     │           │ GameMan             │         │ GameMan        │
│ ─────────────│           │ ─────────────────── │         │ ────────────── │
│ position      │           │ warp_requested      │         │ dest_entity_id │
│ (x, y, z)     │           │ (bool @ 0x10)       │         │ (u32 @ 0x3C)   │
│ map_id        │           └──────────┬──────────┘         └───────┬────────┘
│ anim_id       │                      │                            │
└───────┬───────┘                      │                            │
        │                              │                            │
        ▼                              ▼                            ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                            WarpTracker::check_warp()                          │
└───────────────────────────────────────────────────────────────────────────────┘
        │
        │  1. TIMEOUT CHECK: If pending_warp exists and > 30s → discard
        │
        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                           2. ENTRY DETECTION                                  │
│                        (three possible triggers)                              │
│                                                                               │
│  Triggers are evaluated in priority order: A → B → C (first match wins)      │
│                                                                               │
│  IMPORTANT: A new pending is NOT created if an existing pending has          │
│  warp_was_requested=true (warp in progress, don't overwrite with animations  │
│  playing on the destination map)                                             │
└───────────────────────────────────────────────────────────────────────────────┘
        │
        ├─────────────────────────────┬─────────────────────────────┬───────────┐
        ▼                             ▼                             ▼           │
┌───────────────────────┐   ┌───────────────────────┐   ┌───────────────────────┐
│  TRIGGER A: ANIMATION │   │  TRIGGER B: FOG RANDO │   │  TRIGGER C: VANILLA   │
│  ─────────────────────│   │  ─────────────────────│   │  ─────────────────────│
│  Known teleport anim  │   │  warp_requested:      │   │  warp_requested:      │
│  just started         │   │    false → true       │   │    false → true       │
│  AND                  │   │  AND                  │   │  AND                  │
│  no active warp       │   │  dest_entity_id ∈     │   │  dest_entity_id != 0  │
│                       │   │    [755890000,        │   │  AND                  │
│  → PendingWarp        │   │     755899999]        │   │  target_grace == 0    │
│    type = anim label  │   │  AND pending = None   │   │  AND not fog rando    │
│    warp_req = false   │   │                       │   │  AND pending = None   │
│    dest_entity = 0    │   │  → PendingWarp        │   │                       │
│                       │   │    type = "FOG_RANDO" │   │  → PendingWarp        │
│                       │   │    warp_req = true    │   │    type = "VANILLA_   │
│                       │   │    dest_entity = val  │   │           WARP"       │
│                       │   │                       │   │    warp_req = true    │
│                       │   │                       │   │    dest_entity = val  │
└───────────────────────┘   └───────────────────────┘   └───────────────────────┘
        │                                                                       │
        └───────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                      3. STATE CAPTURE (if pending_warp exists)                │
│  ─────────────────────────────────────────────────────────────────────────── │
│  When warp_requested becomes true:                                            │
│                                                                               │
│  • FAST TRAVEL CHECK: If target_grace != 0 AND cur_anim is NOT a fog/waygate  │
│      → This is a Fast Travel, not a fog traversal                             │
│      → CLEAR the pending (it was a false positive from an earlier animation)  │
│      → The zone_query flow will handle zone resolution instead                │
│                                                                               │
│  • Otherwise: pending.warp_was_requested = true                               │
│                                                                               │
│  Also:                                                                        │
│  • If pending.dest_entity_id == 0 && dest_entity_id != 0                      │
│      → pending.dest_entity_id = dest_entity_id                                │
│                                                                               │
│  Fog/waygate animations: FogWall (60060), Waygate (60490),                    │
│                          SendingGateBlue (60470), SendingGateRed (60472)      │
└───────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                           4. EXIT DETECTION                                   │
│  ─────────────────────────────────────────────────────────────────────────── │
│  Animation ended (was_in_anim=true → false) AND position readable             │
│  OR                                                                           │
│  Pending warp exists + no animation + position became readable (delayed)      │
│                                                                               │
│  → Create DiscoveryEvent from PendingWarp + exit position                     │
└───────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                           5. VALIDATION (is_valid)                            │
│  ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│                         warp_was_requested == true ?                          │
│                                                                               │
│                          ┌──────────┴──────────┐                              │
│                          │                     │                              │
│                         YES                    NO                             │
│                          │                     │                              │
│                          ▼                     ▼                              │
│                  ┌───────────────┐    ┌───────────────┐                       │
│                  │ VALID         │    │ FALSE POSITIVE│                       │
│                  │ → return Some │    │ → return None │                       │
│                  └───────────────┘    └───────────────┘                       │
│                                                                               │
│  Filters false positives like:                                                │
│  • POST_BOSS_WARP with dest_entity=0 (cutscene without actual warp)          │
│  • LIURNIA_TOWER_DOOR with dest_entity=0 (door without randomization)        │
│  • Vanilla waygates (entity=34112160, etc.) without warp_requested           │
└───────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ Some(DiscoveryEvent)
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                      6. SEND TO SERVER (if connected)                         │
│  ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│  TrackerSession::update() calls server.send_discovery()                       │
│  → Sends discovery_v2 message via WebSocket                                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Key steps**:
1. **Entry Detection**: Two triggers can start tracking - animation start OR entity-based (warp_requested + fog rando entity ID)
2. **State Capture**: Poll `warp_requested` and `dest_entity_id` each frame while pending
3. **Exit Detection**: When animation ends AND position is readable, create discovery
4. **Validation**: Filter by `warp_was_requested` - ALL discoveries must have had this flag true
5. **Send**: If connected, send `discovery_v2` message to server

### Coffin Transport

Coffins have no distinctive animation and are currently not explicitly detected. If Fog Rando randomizes coffin destinations, the warp would be classified as "OTHER" transport type.

### Fast Travel

Fast travel (via map menu) is **not tracked as a discovery** by the mod - it's not a fog gate traversal. However, the mod does capture the grace entity ID when fast travel is initiated.

**Key distinction**: The mod captures the grace entity ID via a function hook, NOT from memory offset `0x3C`. These contain different values:
- Grace entity ID (from hook): Like `1042362951` (The First Step)
- `initial_area_entity_id` (0x3C): Spawn point ID like `14000981` (different format, used for fog gates)

After fast travel completes (loading screen exits), the mod sends a `zone_query` message that includes the `grace_entity_id`. This allows the server to precisely resolve the destination zone using the grace-to-zone mapping, bypassing position-based resolution which can be ambiguous when multiple zones share the same coordinates.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Fast Travel Timeline                                 │
├──────────────────────────────────────────────────────────────────────────────┤
│  t=0            t=0.1s           t=1-2s           t=2s                       │
│   │               │                │               │                         │
│   ▼               ▼                ▼               ▼                         │
│ Player        Game calls        Loading        zone_query                    │
│ selects       lua_warp()        screen         sent with                     │
│ grace         Hook captures     (pos=None)     grace_entity_id               │
│               grace_entity_id                                                │
│                                                                              │
│ ──────▶ HOOK CAPTURE ─────────────────────────▶ SEND zone_query ──────────▶  │
│         (warp_hook stores                       (include grace_entity_id)    │
│          grace entity ID)                                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

The grace entity ID is captured by the warp hook and stored until the `zone_query_ack` is received from the server, then cleared. This ensures the ID remains available if the query needs to be retried.

### Warp Validation

ALL discoveries are validated by checking if `warp_requested` was true at some point during the warp. This universal validation filters out false positives across all animation types:

- **Cutscene animations** (`POST_BOSS_WARP`, `LIURNIA_TOWER_DOOR`) that can play without an actual warp
- **Vanilla waygates** that may trigger the animation detection but aren't randomized fog gates

The tracker monitors `GameMan.warp_requested` each frame while a warp is pending and records if it ever becomes true. A discovery is only sent if `warp_was_requested == true`.

**Example false positives** (filtered):
```
Animation: LIURNIA_TOWER_DOOR (12202126)
Entry: m43_01_00_00 (-90.1, 357.2, 22.1)
Exit:  m43_01_00_00 (-71.6, 347.8, 16.9)
warp_requested: never true
→ Discarded (cutscene animation without actual warp)

Animation: WAYGATE (60490)
Entry: m60_42_36_00 (123.4, 56.7, 89.0)
Exit:  m60_41_35_00 (234.5, 67.8, 90.1)
dest_entity: 34112160 (vanilla entity, not fog rando)
warp_requested: never true
→ Discarded (vanilla waygate, not a randomized fog gate)
```

Empirical testing has shown that ALL valid fog rando warps have `warp_requested=true`, making this a reliable universal filter.

## Warp Hook (Grace Entity ID Capture)

The mod hooks the game's `lua_warp` function to capture the grace entity ID when the player initiates fast travel from the map menu.

### Why a Hook?

The GameMan offset `0xB3C` (documented as `target_grace`) returns 0 in practice. Investigation of `fromsoftware-rs` revealed that offset `0xB30` is actually an `F32Vector3` (coordinates), not an entity ID. No other tool (practice-tool, EldenRingTool) successfully reads the grace destination from memory - they all use hardcoded grace databases.

The practice-tool revealed that the game calls a `lua_warp` function with the grace entity ID as the third parameter:

```rust
type WarpFn = extern "system" fn(arg1: u64, arg2: u64, grace_id_minus_1000: u32);
```

### Implementation

The hook is implemented using the `retour` crate (a maintained fork of `detour-rs`):

```rust
// warp_hook.rs
static CAPTURED_GRACE_ENTITY_ID: AtomicU32 = AtomicU32::new(0);

unsafe extern "system" fn warp_hook(arg1: u64, arg2: u64, grace_id_param: u32) {
    // The game passes grace_entity_id - 0x3e8 (1000)
    let grace_entity_id = grace_id_param.wrapping_add(0x3e8);
    CAPTURED_GRACE_ENTITY_ID.store(grace_entity_id, Ordering::SeqCst);

    // Call original function
    WARP_DETOUR.get().unwrap().call(arg1, arg2, grace_id_param);
}
```

### Function Address

The `lua_warp` function address is provided by `libeldenring`, which maintains AOB (Array of Bytes) patterns for all supported game versions. The actual function is at `lua_warp + 2` (skipping a RET instruction from the previous function).

Pattern used by libeldenring:
```
C3 ?? ?? ?? ?? ?? ?? 57 48 83 EC ?? 48 8B FA 44
```

### Data Flow

1. **Hook Installation**: At DLL startup, the hook is installed on `lua_warp`
2. **Fast Travel**: When the player selects a grace, the game calls `lua_warp(arg1, arg2, grace_id - 1000)`
3. **Capture**: The hook intercepts the call and stores `grace_id` in an atomic variable
4. **Frame Capture**: `FrameSnapshot` reads from `warp_hook::get_captured_grace_entity_id()`
5. **Zone Query**: After loading completes, the captured ID is included in `zone_query`
6. **Clear**: After sending, the captured value is cleared for the next warp

### Files

- `mod/src/eldenring/warp_hook.rs` - Hook implementation
- `mod/src/dll/frame_state.rs` - Integration with frame snapshot
- `mod/src/dll/tracker.rs` - Hook installation and clear after use

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
    entry: PlayerPosition,        // Position when warp started
    destination_entity_id: u32,   // Captured from GameMan (may be 0 initially)
    transport_type: &'static str, // "FOG", "WAYGATE", "FOG_RANDO", etc.
    created_at: Instant,          // For timeout detection (30s max)
    warp_was_requested: bool,     // Whether warp_requested was ever true
}
```

State transitions:

```
                            ┌─────────────────────────┐
                            │     IDLE                │
                            │ (pending_warp = None)   │
                            └───────────┬─────────────┘
                                        │
               ┌────────────────────────┴────────────────────────┐
               │                                                 │
    Teleport animation starts                      warp_requested becomes true
    (was_in_teleport_anim: false→true)             AND dest_entity ∈ [755890000-755899999]
    AND no active warp in progress                               │
               │                                                 │
               ▼                                                 ▼
    ┌─────────────────────────┐                    ┌─────────────────────────┐
    │ PENDING (animation)     │                    │ PENDING (entity)        │
    │ transport_type = label  │                    │ transport_type =        │
    │ warp_was_requested=false│                    │   "FOG_RANDO"           │
    │ dest_entity = 0         │                    │ warp_was_requested=true │
    └───────────┬─────────────┘                    │ dest_entity = captured  │
                │                                  └───────────┬─────────────┘
                └────────────────────┬─────────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────────────┐
                            │   PENDING (polling)     │
                            │ Each frame:             │
                            │ - Track warp_requested  │
                            │ - Capture dest_entity   │
                            │ - Check timeout (30s)   │
                            │ - Detect Fast Travel    │
                            └───────────┬─────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
    Fast Travel detected         Animation ends +           Timeout (30s)
    (target_grace != 0           position readable
     AND cur_anim not            OR position becomes
     fog/waygate)                readable (delayed)
           │                            │                            │
           ▼                            ▼                            ▼
    ┌─────────────────┐       ┌─────────────────────────┐   ┌─────────────────┐
    │ Clear pending   │       │     VALIDATE            │   │ Discard         │
    │ (zone_query     │       │ warp_was_requested?     │   │ (stale pending) │
    │ handles zone)   │       └───────────┬─────────────┘   └─────────────────┘
    └─────────────────┘                   │
           │                   YES        │        NO
           │                    │         │         │
           │                    ▼         │         ▼
           │          ┌─────────────────┐ │ ┌─────────────────┐
           │          │ Send discovery  │ │ │ Discard         │
           │          │ Clear pending   │ │ │ (false positive)│
           │          └─────────────────┘ │ └─────────────────┘
           │                              │
           └──────────────────────────────┴──────────────────────────┐
                                                                     │
                                                                     ▼
                                                    ┌─────────────────────────┐
                                                    │     IDLE                │
                                                    │ (pending_warp = None)   │
                                                    └─────────────────────────┘
```

**Note**: When a pending has `warp_was_requested=true`, new teleport animations (e.g., PostBossWarp, LiurniaDivineTower playing on the destination map) do NOT create new pendings. This prevents losing the original pending during the loading/arrival phase.

**Timeout handling**: If a pending warp stays unresolved for more than 30 seconds, it's discarded to avoid stale state.

**Delayed exit handling**: If the animation ends while position is still unreadable (loading screen), the pending warp is kept and the discovery is sent on the next frame when position becomes readable.

## Entity IDs in FogMod

FogMod uses entity IDs in range `755890000-755899999` for its spawn points. Each fog gate transition involves two entity IDs:

### Destination Entity (dest_entity) - Fog Gates Only

The spawn point on the **destination side** of the fog gate. This is the entity ID used by the `WarpPlayer` instruction (2003:14) to teleport the player.

- **Memory offset**: `GameMan + 0x3C` (`initial_area_entity_id`)
- **Captured from**: `WarpDetector::get_destination_entity_id()` when `warp_requested` becomes true
- **Used for**: Zone resolution (map lookup via entity_mapping)
- **Format**: `755890xxx` (FogMod spawn point range)

**Note**: This is different from the grace entity ID used for fast travel (see GameMan offsets above).

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

The destination entity ID handling depends on how the warp was triggered:

**Animation-triggered warps**: The entity ID is polled each frame until non-zero:

```rust
// Capture dest_entity_id when available (happens after animation start for fog gates)
if let Some(ref mut pending) = self.pending_warp {
    if pending.destination_entity_id == 0 {
        let dest_entity_id = warp_detector.get_destination_entity_id();
        if dest_entity_id != 0 {
            pending.destination_entity_id = dest_entity_id;
        }
    }
}
```

**Entity-triggered warps**: The entity ID is captured immediately when the trigger fires (since we already checked it's in the fog rando range).

The polling approach for animation-triggered warps is necessary because:
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
  "source_zone": "Limgrave - Stormhill",
  "source_zone_key": "limgrave_stormhill",
  "target_map_id": "m11_05_00_00",
  "target_pos": {"x": 150.0, "y": 60.0, "z": 180.0},
  "target_play_region_id": 2097152,
  "warp_type": "FOG",
  "destination_entity_id": 755890123
}
```

| Field | Description |
|-------|-------------|
| `destination_entity_id` | Key for entity mapping lookup on the server |
| `source_zone` | Cached zone display name from previous server response (optional) |
| `source_zone_key` | Cached zone internal key (optional, for future migration) |

### Source Zone Disambiguation

The mod caches zone information from server responses (`discovery_v2_ack` and `zone_query_ack`). When sending a new discovery, it includes the cached zone info as `source_zone` and `source_zone_key`.

The server uses this information to **prioritize** matching candidates - if the mod's cached zone matches a candidate, that candidate is moved to the front of the list. This helps resolve ambiguous cases where multiple zones could match the source position.

**Key behavior**:
- Fields are optional for backward compatibility
- Server prioritizes (not filters) matching candidates
- Both display name and internal key are sent to prepare for future key-based matching

## Zone Query Message

When the player exits a loading screen without a pending warp (fast travel, death, initial load), the mod sends a `zone_query` to request the current zone information:

```json
{
  "type": "zone_query",
  "map_id": "m60_42_36_00",
  "pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "play_region_id": 1048576,
  "grace_entity_id": 1042362951
}
```

The `grace_entity_id` field is optional and only present for fast travel:
- **Fast travel**: Contains the grace entity ID (e.g., `1042362951` for "The First Step")
- **Death/respawn**: Not present (server uses position-based resolution)
- **Initial load**: Not present

### Grace Entity ID Format

Grace entity IDs follow patterns based on location type:

| Type | Format | Example |
|------|--------|---------|
| Overworld | `10XXYY295x` | `1042362951` → m60_42_36_00 (The First Step) |
| Legacy dungeon | `AABB0295x` | `10002958` → m10_00 (Stormveil Main Gate) |
| Mini-dungeon | `1XX295x` | `1002950` → m31_00 (Murkwater Cave) |
| Roundtable Hold | `11102950` | `11102950` → Table of Lost Grace |

The server maintains a mapping of 254 grace entity IDs to zone names in `server/data/graces.json`.

### Zone Resolution Priority

When handling `zone_query`, the server resolves the zone in this order:

1. **Grace entity ID** (most precise for fast travel)
2. **Col/play_region_id** (precise for dungeons)
3. **Position-based** (fallback, may have duplicates)

Only discovered zones are returned to avoid spoilers.

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

The mod reads `fog_rando_tracker.toml` from the DLL directory:

```toml
[server]
enabled = true
url = "https://fog.example.com"
mod_token = "your-token-here"
game_id = "uuid-of-game"
auto_reconnect = true

[keybindings]
toggle_ui = "F9"
toggle_debug = "F10"
toggle_exits = "F11"

[overlay]
font_path = "segoeui.ttf"
font_size = 16.0
background_color = "#141414"
background_opacity = 0.7
text_color = "#FFFFFF"
text_disabled_color = "#808080"
discovered_color = "#80FF80"
undiscovered_color = "#B3B3B3"
show_border = false
border_color = "#404040"
status_template = "{zone}$>{status} {discovered}/{total}"
zone_unknown_text = "(traverse a fog to identify)"
# icon_size = 16.0  # Optional, defaults to font_size
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
