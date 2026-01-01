# Grace Entity ID Matching

This document describes how grace entity IDs are used for precise zone resolution during fast travel, and how `graces.json` was built.

## Overview

When a player fast travels to a grace, the mod captures the grace entity ID via a hook on the `lua_warp` function. This ID is sent to the server in `zone_query` messages, allowing precise zone resolution without relying on position-based heuristics.

## Grace Entity ID Format

Grace entity IDs are derived from the `DebugText` entries in `fog.txt`. There are two formats:

### 6-Digit DebugText (Dungeons)

Format: `NNNNNN - Region - Grace Name`

Example: `100001 - Stormhill - Margit, the Fell Omen`

**Entity ID Formula:**
```
base_entity_id = (debug_num // 100) * 10000 + 950 + (debug_num % 100)
grace_entity_id = base_entity_id + 2000
```

Example calculation:
```
debug_num = 100001
base = (100001 // 100) * 10000 + 950 + (100001 % 100)
     = 1000 * 10000 + 950 + 1
     = 10000951
grace_entity_id = 10000951 + 2000 = 10002951
```

### 8-Digit DebugText (Overworld)

Format: `6XXYYZZZZ - Region - Grace Name`

Where `XX` and `YY` encode map tile coordinates (corresponding to `m60_XX_YY_00`).

Example: `61423601 - Limgrave - The First Step`

**Entity ID Formula:**
```
D3D4 = digits 3-4 (map X coordinate)
D5D6 = digits 5-6 (map Y coordinate)
D7D8 = digits 7-8 (grace index)

base_entity_id = 10{D3D4}{D5D6}0950 + D7D8
grace_entity_id = base_entity_id + 2000
```

Example calculation:
```
debug_text = "61423601"
D3D4 = 42, D5D6 = 36, D7D8 = 01

base = 1042360950 + 1 = 1042360951
grace_entity_id = 1042360951 + 2000 = 1042362951
```

The map ID can also be derived: `m60_{D3D4}_{D5D6}_00` → `m60_42_36_00`

## Zone Matching Strategy

When building `graces.json`, zones are determined using the following priority:

1. **Explicit `Area:` field** in fog.txt → use zone display name from that area
2. **"{Region} - {Grace Name}"** pattern → check if this exists as a zone in fog.txt
3. **Grace name alone** → check if it exists as a standalone zone
4. **Region fallback** → map region to generic zone (e.g., "Caelid", "Limgrave")

Example matches:
- "Aqueduct-Facing Cliffs" in "Nokron, Eternal City" → "Nokron - Aqueduct-Facing Cliffs"
- "Dragon Temple" in "Crumbling Farum Azula" → "Farum Azula - Dragon Temple"
- "Haligtree Town" → "Haligtree Town" (standalone)

## FogMod Custom Graces

Fog Gate Randomizer adds custom graces (bonfires) at strategic locations. These have entity IDs that don't follow the standard formula and must be added manually:

| Grace Name | Entity ID | Zone |
|------------|-----------|------|
| Academy Courtyard | 14002955 | Academy of Raya Lucaria after Red Wolf |
| After Redmane Castle Plaza | 1051362952 | Redmane Castle |
| Before Praetor's Throne | 16002955 | Volcano Manor after Temple of Eiglay |
| Siofra Aqueduct | 12022973 | Siofra Aqueduct |
| Divine Tower of East Altus: Start | 34142952 | Divine Tower of East Altus Start |
| Shadow Keep Moat | 21002955 | Shadow Keep |
| After Dragon Temple | 13002961 | Farum Azula Rooftop and Bridge |

## File Structure

`server/data/graces.json`:
```json
{
  "mapping": {
    "1042362951": {
      "grace_name": "The First Step",
      "zone": "Limgrave",
      "map_id": "m60_42_36_00"
    },
    ...
  }
}
```

## Resolution Flow

```
Player fast travels to grace
         │
         ▼
Mod hooks lua_warp, captures grace_entity_id
         │
         ▼
Mod sends zone_query with grace_entity_id
         │
         ▼
Server looks up grace_entity_id in graces.json
         │
         ├─► Found: Use zone from mapping
         │            │
         │            ▼
         │   Verify zone is discovered in current game
         │            │
         │            ├─► Yes: Return zone
         │            └─► No: Fall back to position-based resolution
         │
         └─► Not found: Fall back to position-based resolution
```

## Entity ID Collisions

The 8-digit entity ID formula ignores D1D2 (the "6x" prefix), which distinguishes base game maps (61/64) from DLC maps (68). This causes 6 pairs of graces to share the same entity ID:

| Entity ID | Base Game Grace | DLC Grace |
|-----------|-----------------|-----------|
| 1046402950 | Smoldering Church (Caelid) | Gravesite Plain (Gravesite Plain) |
| 1048372950 | Caelid Highway South (Caelid) | Cerulean Coast Cross (Cerulean Coast) |
| 1048392950 | Smoldering Wall (Caelid) | Cerulean Coast (Cerulean Coast) |
| 1048432950 | Pillar Path Cross (Gravesite Plain) | Divided Falls (Abyssal Woods) |
| 1049392950 | Sellia Backstreets (Caelid) | Grand Altar of Dragon Communion (Jagged Peak) |
| 1050382950 | Church of the Plague (Caelid) | Finger Ruins of Rhia (Cerulean Coast) |

Additionally, FogMod's "Before Praetor's Throne" uses entity ID 16002955, which collides with vanilla "Audience Pathway" in Volcano Manor.

When a collision occurs, the server falls back to position-based resolution after the grace lookup returns a zone not in the player's discovered zones.

## Building graces.json

The file was built by parsing `fog.txt`:

1. Extract all `DebugText` entries for graces
2. Apply the appropriate entity ID formula based on format
3. Determine zone using the matching strategy above
4. Add FogMod custom graces manually
5. Manual corrections for edge cases

**Counts:**
- 414 vanilla graces in fog.txt
- 6 pairs share entity IDs (base game/DLC collisions)
- 1 FogMod ID collides with vanilla "Audience Pathway"
- **graces.json total: 414 entries** (407 unique vanilla + 7 FogMod custom)

## Updating graces.json

When adding new graces or fixing zone mappings:

1. Identify the grace's DebugText number in fog.txt
2. Calculate the entity ID using the appropriate formula
3. Determine the correct zone (check fog.txt for `Area:` field or use naming patterns)
4. Add/update the entry in graces.json
5. Test by fast traveling to that grace in-game

## Death/Respawn Handling

When a player dies or uses Memory of Grace (réminiscence), there is no `lua_warp` hook to capture a grace entity ID. The respawn can occur at:

1. **Stake of Marika**: Player respawns near where they died
2. **Last rested grace**: Player respawns at the last grace they rested at

### Same-Map Fallback

Since we don't have a grace entity ID for respawns, the server may fail to resolve the zone. To handle this gracefully, the mod implements a **same-map fallback**:

```
After loading screen ends:
  - Send zone_query to server
  - If server returns zone: use it
  - If server returns null AND map_id unchanged: keep current zone (fallback)
  - If server returns null AND map_id changed: clear zone display
```

**Rationale:**
- Stake of Marika respawns are always on the same map → same-map fallback applies
- Same-zone grace respawns (common case) → same-map fallback applies
- Different-zone grace respawns without resolution → zone is cleared (honest "unknown")

This is a display-only fallback for the in-game overlay. It doesn't affect link discovery, which only happens via fog gate traversals with proper entity IDs.
