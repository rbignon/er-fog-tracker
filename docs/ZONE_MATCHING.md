# Zone Matching

This document describes how the server resolves zone names from mod discovery events and matches them to spoiler log entries.

## The Problem

The mod sends:
```json
{
  "source_map_id": "m10_01_00_00",
  "source_pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "target_map_id": "m11_05_00_00",
  "target_pos": {"x": 150.0, "y": 60.0, "z": 180.0},
  "destination_entity_id": 755890123
}
```

The spoiler log has:
```
Limgrave - Stormhill (near the broken bridge) -> Liurnia - Lake (by the telescope)
```

We need to match the mod's map/position data to the spoiler log's zone names.

## Data Files

### fog.txt

Maps internal zone names to display names, plus ASide/BSide detail texts.

```yaml
- Name: m10_01_stormhill
  Text: Limgrave - Stormhill
  Maps: m10_01_00_00 m10_01_00_01
  ASide:
    Area: m10_01_stormhill
    Text: near the broken bridge
  BSide:
    Area: m10_01_stormhill_east
    Text: by the merchant
```

| Field | Description |
|-------|-------------|
| `Name` | Internal zone key |
| `Text` | Display name (shown in spoiler log) |
| `Maps` | List of map_ids that contain this zone |
| `ASide/BSide` | Detail texts with their associated zones |

### submaps.txt

Position-based rules for disambiguating zones within a map.

```yaml
- Map: m10_01_00_00
  - Name: Upper Stormhill
    Area: m10_01_stormhill_upper
    YAbove: 100.0
  - Name: Lower Stormhill
    Area: m10_01_stormhill_lower
    YBelow: 50.0
  - Name: Stormhill
    Area: m10_01_stormhill
    # No conditions = default
```

| Condition | Meaning |
|-----------|---------|
| `XAbove: N` | Match if x > N |
| `XBelow: N` | Match if x < N |
| `YAbove: N` | Match if y > N |
| `YBelow: N` | Match if y < N |
| `ZAbove: N` | Match if z > N |
| `ZBelow: N` | Match if z < N |

Rules are checked in order. First match wins. Last rule without conditions is the default.

### foglocations2.txt

Col (play region) to zone mappings.

```yaml
- Name: m10_01_stormhill
  Cols: m10_01_00_00_h001000 m10_01_00_00_h001001
  - Map: m10_01_00_00
    AArea: m10_01_stormhill m10_01_stormhill_east
```

| Field | Description |
|-------|-------------|
| `Cols` | Col identifiers (map_id + play_region) |
| `AArea` | Zones accessible from this fog gate |

## Resolution Strategies

When the mod sends a discovery, the server tries multiple strategies in order:

### 1. Col-Based Matching (Most Precise)

If the mod provides `play_region_id`:
1. Convert to Col format: `h{play_region_id:06x}` (e.g., `h001000`)
2. Look up `(map_id, col)` in foglocations2.txt
3. Returns exact zone for that play region

**Precision**: ~95% when Col is available

### 2. Position-Based Rules (submaps.txt)

If Col lookup fails or unavailable:
1. Look up `map_id` in submaps.txt
2. Check each rule's conditions against position
3. First matching rule → zone name
4. If no match → use default area for that map

**Precision**: ~70% (position boundaries not always perfect)

### 3. Entity Mapping (EMEVD)

If `destination_entity_id` is provided and game has `entity_mapping`:
1. Look up entity (755890xxx) in mapping
2. Get `source_map` and `dest_map` from EMEVD data
3. Use these to prioritize zone candidates

**How it helps**: The entity mapping provides the exact source and destination maps from the EMEVD warp instructions. This helps disambiguate when multiple zones share a map.

```json
{
  "755890123": {
    "source_map": "m10_01_00_00",
    "dest_map": "m11_05_00_00",
    "source_entity": 755890124
  }
}
```

### 4. Zone Candidates (Fallback)

If no exact match:
1. Get all zones associated with `map_id`
2. Order by priority:
   - Position-matched zones first
   - Default zones second
   - Fallback zones third
   - Boss zones last
3. Try matching each candidate against spoiler log

## Zone Pair Matching

After resolving zone names, we need to match against the spoiler log's zone pairs.

### Key-Based Matching (V3)

Zone pairs are enriched with internal keys at game creation:

```json
{
  "source": "Limgrave - Stormhill",
  "destination": "Liurnia - Lake",
  "source_key": "m10_01_stormhill",
  "destination_key": "m11_05_lake"
}
```

Matching process:
1. Get source candidates (internal names)
2. Get target candidates (internal names)
3. Find zone_pair where:
   - `source_key` matches a source candidate, AND
   - `destination_key` matches a target candidate

**Precision**: ~92% with entity mapping, ~82% without

### Display Name Matching (Legacy)

If key-based matching fails, fall back to display name matching:
1. Get source display names
2. Get target display names
3. Find zone_pair where:
   - `source` matches a source display name, AND
   - `destination` matches a target display name

**Precision**: ~60% (display names can be ambiguous)

## Zone Pair Enrichment

At game creation, zone pairs from the spoiler log are enriched with internal keys:

```
┌─────────────────────────────────────────────────────────────┐
│ Spoiler Log Entry                                           │
│ "Limgrave - Stormhill (near the bridge) -> Liurnia - Lake"  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Extract detail text                                 │
│ source_details = "near the bridge"                          │
│ target_details = (none)                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Look up in fog.txt ASide/BSide                      │
│ "near the bridge" → m10_01_stormhill                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Fallback to display name lookup                     │
│ "Liurnia - Lake" → m11_05_lake                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Enriched Zone Pair                                          │
│ {                                                           │
│   "source": "Limgrave - Stormhill",                         │
│   "destination": "Liurnia - Lake",                          │
│   "source_key": "m10_01_stormhill",                         │
│   "destination_key": "m11_05_lake"                          │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```

## Entity Mapping Integration

The entity mapping from EMEVD parsing improves precision by providing exact map information.

### Building the Entity Mapping (Launcher)

```
┌─────────────────────────────────────────────────────────────┐
│ EMEVD Files (event/*.emevd.dcx)                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Parse each file:                                            │
│ 1. Decompress DCX (Deflate/zlib)                            │
│ 2. Parse EMEVD binary format                                │
│ 3. Find WarpPlayer instructions (category=2003, index=14)   │
│ 4. Extract: map_type, destination_entity_id                 │
│ 5. Find source_entity from RotateCharacter (2004:14)        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Entity Mapping                                              │
│ {                                                           │
│   "755890123": {                                            │
│     "source_map": "m10_01_00_00",  // File name             │
│     "dest_map": "m11_05_00_00",    // From map_type         │
│     "source_entity": 755890124     // From RotateCharacter  │
│   }                                                         │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```

### Using Entity Mapping (Discovery)

```
┌─────────────────────────────────────────────────────────────┐
│ Mod sends: destination_entity_id = 755890123                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Look up in entity_mapping:                                  │
│ 755890123 → source_map=m10_01_00_00, dest_map=m11_05_00_00  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Prioritize zone candidates:                                 │
│ 1. Zones with source_map in their Maps list → front         │
│ 2. Other candidates → back                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Match against zone_pairs with reordered candidates          │
│ (More likely to match the correct one first)                │
└─────────────────────────────────────────────────────────────┘
```

### Potential Uses for source_entity (Not Yet Implemented)

The `source_entity` field is stored but not currently used server-side. It could enable:

**1. Bidirectional Link Verification**

Build a reverse index: `source_entity → dest_entity`. For bidirectional fog gates:
- Entry A→B: `dest_entity=X, source_entity=Y`
- Entry B→A: `dest_entity=Y, source_entity=X`

If we find that X's source_entity (Y) appears as another entry's dest_entity, and that entry's source_entity is X, we've confirmed bidirectionality.

```
┌─────────────────────────────────────────────────────────────┐
│ Entity Mapping (indexed by dest_entity)                     │
├─────────────────────────────────────────────────────────────┤
│ 755890100 → {source_map: A, dest_map: B, source_entity: 200}│
│ 755890200 → {source_map: B, dest_map: A, source_entity: 100}│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Reverse Index (source_entity → dest_entity)                 │
├─────────────────────────────────────────────────────────────┤
│ 755890200 → 755890100  (entry 1: source_entity points back) │
│ 755890100 → 755890200  (entry 2: source_entity points back) │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Conclusion: 100 ↔ 200 are a bidirectional pair              │
└─────────────────────────────────────────────────────────────┘
```

**2. Spoiler Log Validation**

Cross-reference spoiler log zone pairs against entity_mapping pairs:
- For each zone_pair (A → B), check if there's a matching (B → A) in entity_mapping
- Flag inconsistencies between spoiler log and EMEVD data

**3. One-Way Link Detection**

If a dest_entity has no corresponding reverse entry (where its source_entity is another entry's dest_entity), the connection is likely one-way.

## Precision Summary

| Strategy | Precision | When Available |
|----------|-----------|----------------|
| Col-based (play_region_id) | ~95% | When mod sends play_region_id |
| Entity mapping + key matching | ~92% | Launcher with EMEVD parsing |
| Key matching only | ~82% | Spoiler log with fog.txt enrichment |
| Position rules (submaps.txt) | ~70% | Always (fallback) |
| Display name matching | ~60% | Always (last resort) |

## Resolution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Mod Discovery Event                                         │
│ map_id, position, play_region_id, destination_entity_id    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
            ┌─────────────────┴─────────────────┐
            │   Col-based lookup available?     │
            └─────────────────┬─────────────────┘
                    Yes ┌─────┴─────┐ No
                        ▼           ▼
              ┌─────────────┐  ┌─────────────────┐
              │ Exact zone  │  │ Position rules  │
              │ from Col    │  │ (submaps.txt)   │
              └──────┬──────┘  └────────┬────────┘
                     │                  │
                     └────────┬─────────┘
                              ▼
            ┌─────────────────────────────────────┐
            │   Entity mapping available?         │
            └─────────────────┬───────────────────┘
                    Yes ┌─────┴─────┐ No
                        ▼           │
              ┌─────────────────┐   │
              │ Prioritize      │   │
              │ candidates by   │   │
              │ source/dest map │   │
              └────────┬────────┘   │
                       └─────┬──────┘
                             ▼
            ┌────────────────────────────────────┐
            │   Try key-based matching           │
            │   (source_key, destination_key)    │
            └─────────────────┬──────────────────┘
                    Found ┌───┴───┐ Not found
                          ▼       ▼
              ┌───────────────┐ ┌───────────────────┐
              │ Return match  │ │ Try display name  │
              │               │ │ matching          │
              └───────────────┘ └───────────────────┘
```

## Troubleshooting

### Discovery Not Matching

1. **Check zone_pairs**: Does the game have the expected connection?
2. **Check enrichment**: Are `source_key`/`destination_key` populated?
3. **Check entity_mapping**: If launcher was used, is the entity in the mapping?
4. **Check logs**: Server logs show resolution attempts with candidates

### Multiple Matches

If multiple zone pairs match the same candidates:
- Server picks the first match in spoiler log order
- This can lead to incorrect matches in rare cases
- Entity mapping helps by narrowing candidates

### Missing Zone Keys

If enrichment fails:
- Check if zone display name is in fog.txt
- Check if detail text matches ASide/BSide entries
- Manual zone_key addition may be needed for edge cases
