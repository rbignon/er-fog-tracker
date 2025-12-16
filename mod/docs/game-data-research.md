# Elden Ring Game Data Research

Documentation of memory structures, animation IDs, and SpEffects discovered during mod development.

## Detection Strategy for Fog Randomizer

### Events to Track (randomized destinations)

| Type | Detection Method | Details |
|------|------------------|---------|
| Fog wall | Animation `60060` | Walk through fog gate |
| Waygate | Animation `60490` | Hand turns blue |
| Sending gate | Animation `60490` | **Same as waygate!** Hand turns blue |
| Coffin | Exclusion + SpEffect verification | No animation, `warp_requested` + `dest_entity_id == 0` |
| Pureblood Knight's Medal | Animation `50340` + Item ID `0x40000870` | Item use (via `tae_queued_use_item`) |

### Events to Track (for position awareness, not randomized)

| Type | Detection Method | Details |
|------|------------------|---------|
| Fast travel | `GameMan.warp_requested` without other events | Menu-based teleport, destination entity ID available |

### Events to Ignore (not randomized)

| Type | Detection Method | Details |
|------|------------------|---------|
| Death | Animation `4xxx` or `20xxx` before BROKEN | Respawn at grace/stake |
| Memory of Grace | Animation `50230` + SpEffect `3226` | TP to last grace (not randomized) |
| Trap chest | Disabled in fog randomizer | N/A |

### Detection Logic

```
1. If animation 60060 detected → FOG WALL (track)
2. If animation 60490 detected → WAYGATE or SENDING GATE (track)
3. If animation 50340 + tae_queued_use_item == 0x40000870 → MEDAL (track)
4. If warp_requested + no animation + dest_entity_id == 0 → COFFIN (track)
   - Secondary verification: SpEffect 4190/4010/4510 (not required, for confirmation)
5. If warp_requested + dest_entity_id != 0 + no animation → FAST TRAVEL (track for position)
6. If animation 4xxx/20xxx → DEATH (ignore)
7. If animation 50230 + SpEffect 3226 → MEMORY OF GRACE (ignore)
```

Note: Animation 60470/60472 from CE table NOT used in practice for sending gates.

### GameMan-based Detection (new)

For fast travel and as a secondary confirmation signal, we use `GameMan.warp_requested`:

```
GameMan + 0x10 = warp_requested (bool)
GameMan + 0x3C = initial_area_entity_id (u32) - destination grace entity ID
GameMan + 0xAC8 = load_target_block_id (u32) - destination map ID
```

This provides:
- A reliable signal that ANY warp is about to happen
- The destination entity ID before the warp (for fast travel, this is the grace entity ID)
- Works for all warp types, not just animation-based ones

## Animation IDs

Source: CE Table (`eldenring_all-in-one_Hexinton-v5.0_ce7.5.ct`)

### Fog Gates
| ID | Description | Usage |
|----|-------------|-------|
| 60060 | "Walk through fog gate, moves cam" | **Fog wall traversal** - trigger discovery |

### Teleporters (Waygates)
| ID | Description | Usage |
|----|-------------|-------|
| 60490 | "Hold out hand, hand turns blue" | **Waygate interaction** - before teleport |

### Sending Gates (Portals)
| ID | Description | Usage |
|----|-------------|-------|
| 60490 | "Hold out hand, hand turns blue" | **Actual sending gate animation (tested!)** |
| 60470 | "Walk through blue portal then go invis" | NOT used in practice (CE table only) |
| 60471 | "Come out other side of blue portal" | Exit animation (visual only?) |
| 60472 | "Walk through red portal then go invis" | NOT used in practice (CE table only) |
| 60473 | "Come out other side of red portal" | Exit animation (visual only?) |

### Item Use Animations
| ID | Description | Usage |
|----|-------------|-------|
| 50340 | Item use (Medal-style) | **Pureblood Knight's Medal** |
| 50230 | Item use (Memory-style) | Memory of Grace (Réminiscence) |

### Death Animations
| ID | Description | Usage |
|----|-------------|-------|
| 20110 | Fall death | Falling |
| 4050, 4000, 4100, 4101 | Death sequence | Various death states |

### Spawn/Appear Animations
| ID | Description | Usage |
|----|-------------|-------|
| 63000 | "Stand up" | Post-teleport spawn (common) |
| 63010 | "Stand up from invis" | Spawn from invisibility |

### Other
| ID | Description | Usage |
|----|-------------|-------|
| 60080 | "Open chest" | Normal chest opening |
| 10000000 | Idle | Common idle state |
| 0 | Idle variant | Sometimes shown as idle |

## SpEffect IDs

### Teleport-Related SpEffects

| ID | Description | When |
|----|-------------|------|
| 502160, 502161 | Pureblood Knight's Medal | Before teleport (not used for detection, using item ID instead) |
| 3226 | Memory of Grace (Réminiscence) | Before teleport |
| 4190, 4010, 4510 | Coffin transport | Secondary verification (exclusion-based detection is primary) |
| 4651, 4601 | Coffin arrival | After teleport |
| 106 | Grace spawn | After fast travel / death / Réminiscence |
| 4289 | Post-teleport effect | After most teleports |
| 19996 | Post-teleport effect | Brief, after most teleports |
| 32 | Unknown | Brief, appears during death |

### Common Persistent SpEffects
| ID | Description |
|----|-------------|
| 6189000 | Always active |
| 100620 | Common |
| 503045 | Common |
| 100000/100001 | Alternates |

### SpEffect stateInfo Values (from CE Table)

These are parameter values that define what a SpEffect does, not SpEffect IDs themselves.

| Value | Description |
|-------|-------------|
| 0 | None |
| 16 | Warp to Grace |
| 17 | Revival |
| 116 | Death |
| 117 | Death: Instant Death animation |
| 161-165 | Warp to Grace (variants) |
| 302 | Warp to Grace |

## Tested Sequences

### Fog Wall (TRACK)
```
60060 (walk through fog) → BROKEN → new PlayerIns → [destination]
```

### Waygate (TRACK)
```
60490 (hand turns blue) → BROKEN → new PlayerIns → 63000 (spawn)
SpEffects after: 4289, 19996
```

### Sending Gate (TRACK)
```
60490 (hand turns blue) → BROKEN → new PlayerIns
SpEffects after: 4289, 19996
Note: Uses SAME animation as waygate! Tested at Volcano Manor → Rykard.
```

### Pureblood Knight's Medal (TRACK)
```
50340 (use item) → SpEffect 502160/502161 → BROKEN → new PlayerIns → 4050 → 63000
SpEffects after: 4289, 19996, 32
```

### Coffin (TRACK)
```
warp_requested=true + no animation + dest_entity_id=0 → BROKEN → new PlayerIns
SpEffects after: 4651, 4601, 4289, 19996

Detection logic:
- Primary: Exclusion-based (warp + no animation + dest_entity_id == 0)
- Secondary: SpEffect 4190/4010/4510 (for confirmation, not required)
- Logs warning if exclusion detects but no known SpEffect (possible new coffin type)
```

### Fast Travel (TRACK for position)
```
warp_requested=true + dest_entity_id != 0 + no animation → BROKEN → new PlayerIns → SpEffect 106 → 63000
SpEffects after: 106, 4289, 19996

Detection logic:
- warp_requested == true (GameMan confirms warp)
- dest_entity_id != 0 (grace entity ID is set via menu)
- No animation (fog/waygate/medal)
```

### Memory of Grace / Réminiscence (IGNORE)
```
50230 (use item) → SpEffect 3226 → BROKEN → new PlayerIns → SpEffect 106 → 63000
SpEffects after: 106, 4289, 19996
```

### Death (IGNORE)
```
20110 (fall) → 4050, 4000, 4100, 4101 (death) → SpEffect 32 → BROKEN → new PlayerIns → SpEffect 106 → 63000
SpEffects after: 106, 4289, 19996
```

## Memory Structures

### PlayerIns Pointer Chain
```
WorldChrMan[player_ins_offset] → PlayerIns
```

- `player_ins_offset`:
  - v1.02 - v1.06: `0x18468`
  - v1.07+: `0x1E508`

### SpEffect Reading
```
PlayerIns[0x178] → SpEffectCtrl
SpEffectCtrl[0x8] → First SpEffect node

Each node:
  +0x8  = SpEffect ID (u32)
  +0x30 = Next node pointer
```

### Key Observations

1. **During teleport/loading**: PlayerIns becomes `0x0` (null), SpEffect chain breaks (BROKEN)
2. **After teleport**: PlayerIns gets a NEW address (not the same as before)
3. **Same behavior for all teleports and death**: PlayerIns goes null during loading

## Item IDs

From EldenRingTool:

| Item | ID (hex) | Base ID |
|------|----------|---------|
| Pureblood Knight's Medal | 0x40000870 | 2160 |
| Memory of Grace | 0x40000073 | 115 |

Format: `0x40000000` prefix = Goods item, lower bits = item ID

## To Test

- [x] Sending gates - **TESTED**: Use animation 60490 (same as waygates), NOT 60470/60472
- [ ] Imbued Sword Key portals (Four Belfries) - likely use 60490 as well

## Implementation

The detection logic is implemented in `mod/src/game_state.rs` using the `TeleportType` enum:

```rust
pub enum TeleportType {
    FogWall,     // animation 60060
    Waygate,     // animation 60490 (includes sending gates)
    Medal,       // animation 50340 + item ID 0x40000870 (via tae_queued_use_item)
    Coffin,      // exclusion-based: warp_requested + no animation + dest_entity_id == 0
    FastTravel,  // GameMan.warp_requested without other events
}
```

Each variant exposes:
- `animation_id()` - Animation ID to detect (None for Coffin, FastTravel)
- `speffect_ids()` - SpEffect IDs required for detection
- `requires_speffect()` - Whether SpEffect check is needed
- `name()` - Log prefix (FOG, WAYGATE, MEDAL, COFFIN, FAST_TRAVEL)
- `is_randomized()` - Whether this teleport type is randomized by Fog Gate Randomizer

**Note**: The enum is the authoritative source for detection IDs. Update it if new values are discovered.

### GameManReader

For reading warp state from GameMan, `mod/src/game_state.rs` provides:

```rust
pub struct GameManReader { ... }

impl GameManReader {
    pub fn is_warp_requested(&self) -> bool;
    pub fn get_destination_entity_id(&self) -> u32;
    pub fn get_destination_map_id(&self) -> u32;
    pub fn get_warp_info(&self) -> Option<WarpInfo>;
}

pub struct WarpInfo {
    pub warp_requested: bool,
    pub destination_entity_id: u32,
    pub destination_map_id: u32,
}
```

This allows detecting fast travel and knowing the destination grace entity ID before the warp completes.

## Additional Structures (from fromsoftware-rs)

Source: [fromsoftware-rs](https://github.com/veeenu/fromsoftware-rs) - reverse engineered structures for Elden Ring.

Note: fromsoftware-rs only supports v2.6.1 (WW/JP) and has heavy dependencies, so we use it as a
reference rather than a direct dependency.

### GameMan Structure

Global game manager with warp-related fields.

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0x10 | bool | `warp_requested` | **IMPLEMENTED** - Set when warp is requested |
| 0x3C | u32 | `initial_area_entity_id` | **IMPLEMENTED** - Destination entity ID (grace ID for fast travel) |
| 0xAB0 | vec4 | `last_load_position` | Position after warp completes |
| 0xAC0 | vec4 | `last_load_orientation` | Orientation after warp |
| 0xAC8 | BlockId | `load_target_block_id` | **IMPLEMENTED** - Target map for next load |

These fields are now used by `GameManReader` in `mod/src/game_state.rs` for:
- Detecting fast travel (warp_requested without other events)
- Getting the destination grace entity ID before the warp completes

### WorldChrMan Structure

Manages all characters including the player.

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0x1E518 | Option<OwnedPtr<PlayerIns>> | `main_player` | Local player pointer |

This confirms our `player_ins_offset` of `0x1E508` for v1.07+ is close - the difference is
due to pointer indirection levels.

### BlockId Bitfield

Map IDs are packed into a u32 bitfield:

```
bits 31-24: area   (m{AA}_XX_YY_ZZ)
bits 23-16: block  (mAA_{XX}_YY_ZZ)
bits 15-8:  region (mAA_XX_{YY}_ZZ)
bits 7-0:   index  (mAA_XX_YY_{ZZ})
```

This matches our `format_map_id()` implementation.

### ChrIns (PlayerIns) Structure

Character instance with item use tracking.

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0x160 | u32 | `tae_queued_use_item` | **IMPLEMENTED** - Item ID being used (animation) |
| 0x178 | ptr | `speffect_ctrl` | SpEffect controller pointer |

The `tae_queued_use_item` field contains the item ID when an item-use animation is playing.
This is more reliable than SpEffect detection for Medal since it directly identifies the item.

### SpEffect Structure (confirmed)

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0x8 | u32 | `param_id` | SpEffect ID |
| 0x30 | ptr | `next` | Next node in linked list |

Confirms our SpEffect reading implementation is correct.

## References

- [Fog Gate Randomizer](https://github.com/thefifthmatt/FogMod)
- [Elden Ring Tool](https://github.com/Jeremielc/EldenRingTool)
- [libeldenring](https://github.com/veeenu/libeldenring)
- [fromsoftware-rs](https://github.com/veeenu/fromsoftware-rs) - detailed struct definitions
- CE Table: `eldenring_all-in-one_Hexinton-v5.0_ce7.5.ct`
