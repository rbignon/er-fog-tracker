# Zone Matching

This document describes how the server resolves zone names from mod discovery events and matches them to spoiler log entries.

## The Problem

The mod sends:
```json
{
  "source_map_id": "m10_01_00_00",
  "source_pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "source_zone_id": "limgrave_stormhill",
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

**Note**: The `source_zone_id` field is the mod's cached zone key from previous server responses. This helps disambiguate the source zone (see Source Zone Prioritization below).

## Game Modes

The Fog Gate Randomizer supports two main game modes that affect which zones are included:

| Mode | Option | Description |
|------|--------|-------------|
| **Dungeon Crawler** | `crawl` | Only dungeons, caves, catacombs, and boss arenas. No overworld traversal. |
| **World Shuffle** | (no `crawl`) | Full world including overworld areas connected via fog gates. |

The mode is detected from the spoiler log's first line (e.g., `Options and seed: crawl dlc ...`).

### Optional Areas Section

Spoiler logs end with an `Optional areas:` section containing zones not required to complete the run:

- **Dungeon Crawler**: Optional areas are **overworld zones** (Limgrave, Caelid, etc.) that players don't traverse since they teleport directly between dungeons. These are **excluded** from parsing.

- **World Shuffle**: Optional areas are **accessible but non-critical zones** (side dungeons, optional bosses) connected via randomized fog gates. These are **included** in parsing so players can discover them.

The parser sets `is_dungeon_crawler=True` when the `crawl` option is present, and only skips the Optional areas section in that mode.

## Data Files

### fog.txt

Maps internal zone names to display names, plus ASide/BSide detail texts.

```yaml
- Name: m10_01_stormhill
  Text: Limgrave - Stormhill
  Aliases: Stormhill
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
| `Aliases` | Alternative display names (semicolon-separated), for reverse lookup |
| `Maps` | List of map_ids that contain this zone |
| `ASide/BSide` | Detail texts with their associated zones |

**Aliases**: Some spoiler logs use shortened zone names (e.g., "Scaduview" instead of "Scaduview - Scadutree Chalice"). The `Aliases` field allows defining alternative names that resolve to the same zone key. Multiple aliases are separated by semicolons.

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

### graces.json

Maps grace entity IDs to zone information. Used for `zone_query` resolution.

```json
{
  "1042362951": {
    "grace_name": "The First Step",
    "zone": "Limgrave",
    "zone_id": "limgrave",
    "map_id": "m60_42_36_00"
  }
}
```

| Field | Description |
|-------|-------------|
| `grace_name` | Human-readable grace name |
| `zone` | Display name (shown to user) |
| `zone_id` | Internal zone key (unambiguous) |
| `map_id` | Map containing this grace |

**Important**: The `zone_id` field provides unambiguous zone resolution. Some display names may be shared by multiple zones (e.g., virtual zones for flame doors), but `zone_id` is always unique. This prevents bugs where `lookup_by_display_name` might return the wrong zone.

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

### 4. Source Zone Filtering (Mod Context)

If the mod provides `source_zone_id` or `source_zone`:
1. Get source zone candidates from map/position resolution
2. Check if any candidate matches the mod's cached zone key/name
3. If match found, **filter to only matching candidate(s)** and mark source as **authoritative**
4. If no match found but `source_zone_id` is valid, **inject it as a candidate**
5. If `source_zone_id` is invalid (unknown zone), keep original list as fallback

**Filter with injection fallback**: When a match is found, only matching candidates are kept. This prevents discovering multiple links when only one fog gate was traversed. When no match is found but the mod provides a valid `source_zone_id`, that zone is injected at the front of the candidate list.

```
┌─────────────────────────────────────────────────────────────┐
│ Case 1: Match found (exclusive filter)                       │
│ candidates = [zone_a, zone_b, zone_c]                       │
│ Mod sends: source_zone_id = "zone_b"                        │
│ Result: candidates = [zone_b]  (others filtered out)        │
│ Source marked as AUTHORITATIVE                               │
├─────────────────────────────────────────────────────────────┤
│ Case 2: No match, valid zone (inject)                        │
│ candidates = [zone_a, zone_b, zone_c]                       │
│ Mod sends: source_zone_id = "zone_x"  (valid but not here)  │
│ Result: candidates = [zone_x, zone_a, zone_b, zone_c]       │
├─────────────────────────────────────────────────────────────┤
│ Case 3: No match, invalid zone (fallback)                    │
│ candidates = [zone_a, zone_b, zone_c]                       │
│ Mod sends: source_zone_id = "unknown"  (not in fog.txt)     │
│ Result: candidates = [zone_a, zone_b, zone_c]  (unchanged)  │
└─────────────────────────────────────────────────────────────┘
```

**Why injection helps**: Some fog gates are physically located in a dungeon map but conceptually considered to be in an overworld zone. For example, the fog gate at the Gaol Cave entrance:
- Is physically in map `m31_21_00_00` (Gaol Cave dungeon)
- But the spoiler log says `source: "Caelid"` (overworld zone)
- The zone resolver only returns Gaol Cave zones for `m31_21_00_00`
- The mod knows the player was in "Caelid" (from previous server response)
- Injecting "caelid" as a candidate enables the match to succeed

**Why this helps**: After traversing a fog gate, the mod knows what zone it was in (from the server's `discovery_v2_ack` or `zone_query_ack`). When the player traverses another fog gate from the same zone, this cached info helps the server pick the correct source candidate, preventing spurious multi-link discoveries.

#### Authoritative Source and Entity Mapping Interaction

When the mod's `source_zone_id` matches a candidate, that source is marked as **authoritative**. This affects entity mapping expansion:

- **Without authoritative source**: Entity mapping can expand source candidates by adding zones from the EMEVD source map. This helps when the mod reports a different tile than where the fog gate is defined.

- **With authoritative source**: The mod's zone is **trusted completely** in the initial search. Entity_mapping expansion is NOT included initially, preventing false discoveries when the expansion adds a parent zone (e.g., "Liurnia") while the mod reports a specific sub-zone (e.g., "liurnia_evergaol_bols").

**Two-phase search** (when authoritative source):
1. **Initial search**: Only the mod's authoritative zone is used
2. **Fallback 1**: If no match found, retry with entity_mapping expanded zones

This approach prevents false discoveries like `liurnia → isolated_tower` when the player was actually in `liurnia_evergaol_bols` (an evergaol within Liurnia).

```
┌─────────────────────────────────────────────────────────────┐
│ Case A: Match found with mod's zone (common case)            │
│                                                              │
│ Step 1: Mod sends source_zone_id = "liurnia_evergaol_bols"  │
│         Entity mapping would add "liurnia" (parent zone)    │
│                                                              │
│ Step 2: Initial search with mod's zone ONLY                  │
│         source_candidates = ["liurnia_evergaol_bols"]       │
│         (entity_mapping NOT included)                        │
│                                                              │
│ Step 3: Find match                                           │
│         → liurnia_evergaol_bols → leyndell2_bedchamber ✓    │
│                                                              │
│ Result: Single correct discovery (no false liurnia match)    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Case B: No match with mod's zone, fallback needed            │
│                                                              │
│ Step 1: Mod sends source_zone_id = "storehouse"             │
│         Entity mapping adds ["storehouse_premessmer", ...]  │
│                                                              │
│ Step 2: Initial search with mod's zone ONLY                  │
│         source_candidates = ["storehouse"]                  │
│         → No match found                                     │
│                                                              │
│ Step 3: Fallback 1 - retry with entity_mapping expansion     │
│         source_candidates = ["storehouse",                  │
│                              "storehouse_premessmer", ...]  │
│         → storehouse_premessmer → ainsel found ✓            │
│                                                              │
│ Result: Correct discovery via fallback                       │
└─────────────────────────────────────────────────────────────┘
```

**Additional fallback mechanisms**: If still no matching zone link is found after Fallback 1, additional fallbacks (preexisting-adjacent expansion, target expansion) are applied to find a valid match.

**Note for targets**: Target candidates use entity mapping expansion as a **strict fallback** mechanism. The server first tries matching with position-based candidates only. If no match is found, it retries with entity mapping expansion. This prevents false discoveries when multiple zones share the same destination map (e.g., the siofra→volcano_pathway bug where entity_mapping added volcano_pathway to target candidates even though the player went to volcano_town).

### 4b. Animation-Based Filtering

Some fog gates require a specific animation to access (e.g., the Pureblood Knight's Medal). These zones should only be candidates when that animation is used.

The `Animation:` field in `fog.txt` marks zones that require a specific warp type:

```yaml
# In fog.txt - Warp definition for Pureblood Knight's Medal
- Name: 12052021
  ID: 12052021
  Area: m12_05_00_00
  Animation: Medal
  ASide:
    Area: chapel_start
```

**Filtering logic**:
- **Negative filter**: When `warp_type` differs from the required animation, exclude zones with that requirement. Example: traversing a `FogWall` in Mohgwyn Palace excludes `chapel_start` (which requires `Medal`).
- **Positive filter**: When `warp_type` matches, keep only zones requiring that animation. (Currently unused since `Medal` warps have a dedicated handler, but the code supports future animation types.)

```
┌─────────────────────────────────────────────────────────────┐
│ Player traverses FogWall in Mohgwyn Palace (m12_05_00_00)    │
│ candidates = [chapel_start, mohgwyn_postboss, mohgwyn]      │
│                                                              │
│ chapel_start requires Animation: Medal                       │
│ warp_type = "FogWall" ≠ "Medal"                             │
│                                                              │
│ Result: candidates = [mohgwyn_postboss, mohgwyn]            │
│ (chapel_start excluded - can only be reached via Medal)     │
└─────────────────────────────────────────────────────────────┘
```

**Note**: The `Medal` warp type has a dedicated handler (`_handle_medal_discovery`) that bypasses normal candidate resolution entirely, since the Medal can be used from any zone. The animation filter primarily serves to exclude Medal-only zones from normal fog wall traversals.

### 4c. Preexisting-Adjacent Zone Expansion

When the mod's authoritative source zone doesn't match any spoiler log link, the server expands source candidates to include zones reachable via **preexisting links** (vanilla doors, elevators, ladders).

**Scenario**: Player walks through a vanilla door before using a randomized fog gate:

```
┌─────────────────────────────────────────────────────────────┐
│ Player is in "Prison Town Church" (volcano_pretown)          │
│ Player walks through one-way door to "Prison Town"           │
│ Player uses randomized fog gate in Prison Town               │
│                                                              │
│ Mod sends: source_zone_id = "volcano_pretown" (cached)       │
│ Spoiler log has: volcano_town → limgrave_tunnels_boss        │
│                                                              │
│ Problem: No match for volcano_pretown as source              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Fallback: Preexisting-adjacent expansion                     │
│                                                              │
│ 1. Get zones reachable via preexisting from volcano_pretown  │
│    → {volcano_pretown, volcano_town}  (via one-way door)    │
│                                                              │
│ 2. Add volcano_town to source candidates                     │
│    → ["volcano_pretown", "volcano_town"]                    │
│                                                              │
│ 3. Retry matching                                            │
│    → Found: volcano_town → limgrave_tunnels_boss ✓          │
└─────────────────────────────────────────────────────────────┘
```

**Why this helps**: The mod caches the player's zone from previous server responses. When the player walks through a vanilla game connection (not a randomized fog gate), the cached zone may become stale. This fallback handles that case by checking adjacent zones.

**Note**: This fallback traverses **all** preexisting links, not just discovered ones. This is intentional because vanilla doors/elevators may not be explicitly tracked as "discovered" preexisting links, but the player can still physically traverse them.

### 5. Zone Candidates (Fallback)

If no exact match:
1. Get all zones associated with `map_id`
2. Order by priority:
   - Position-matched zones first
   - Default zones second
   - Fallback zones third
   - Boss zones last
3. Try matching each candidate against spoiler log

### 6. Grace-Based Resolution (zone_query)

For `zone_query` messages (when player rests at a grace), resolution uses the `zone_id` directly from graces.json:

```
┌─────────────────────────────────────────────────────────────┐
│ Mod sends: zone_query with grace_entity_id = 35002950       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Lookup in graces.json:                                       │
│ 35002950 → zone_id = "sewer_mohg", zone = "Mohg, the Omen"  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Check if zone_id is discovered:                              │
│ "sewer_mohg" in discovered_zones? → Yes → Return zone info  │
└─────────────────────────────────────────────────────────────┘
```

**Why zone_id matters**: The display name "Mohg, the Omen" is shared by two zones:
- `sewer_mohg` - the main boss arena
- `sewer_mohg_flame` - a virtual zone for the flame door

Using `zone_id` directly avoids ambiguity from `lookup_by_display_name`.

### 7. Sibling Map Fallback

When a map has **no zones at all** (step 4 returns empty), the resolver extends the search to sibling maps. This handles cases where the mod reports a map variant not explicitly listed in fog.txt.

**Sibling prefix logic**:
- **Overworld tiles** (`m60_*`, `m61_*`): Use tile prefix (e.g., `m61_44_45_16` → siblings `m61_44_45_*`)
- **Dungeon/legacy maps**: Use area prefix (e.g., `m21_03_00_00` → siblings `m21_*`)

**Example**: The mod reports `m61_44_45_16` but fog.txt only lists zones for `m61_44_45_00`. The sibling fallback finds zones from `m61_44_45_00` and uses them as candidates.

**Important**: This fallback only activates when there are NO direct candidates. If the map has zones but not the target zone, use data fixes in fog.txt instead (see Troubleshooting).

## Zone Link Matching

After resolving zone names, we need to match against the spoiler log's zone links.

### Key-Based Matching

Zone links store zone keys in `source_id` and `target_id`:

```json
{
  "source": "Limgrave - Stormhill",
  "source_id": "m10_01_stormhill",
  "target": "Liurnia - Lake",
  "target_id": "m11_05_lake"
}
```

Matching process:
1. Get source candidates (zone keys)
2. Get target candidates (zone keys)
3. Find zone_link where:
   - `source_id` matches a source candidate, AND
   - `target_id` matches a target candidate

**Precision**: ~92% with entity mapping, ~82% without

### Display Name Matching (Removed)

Display name matching is no longer used after the zone_key migration.
If key-based matching fails, the server logs a resolution failure and skips discovery.

## Zone Link Enrichment

At game creation, zone links from the spoiler log are enriched with zone keys:

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
│ Enriched Zone Link                                          │
│ {                                                           │
│   "source": "Limgrave - Stormhill",                         │
│   "source_id": "m10_01_stormhill",                          │
│   "target": "Liurnia - Lake",                               │
│   "target_id": "m11_05_lake"                                │
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
│ Match against zone_links with reordered candidates          │
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

Cross-reference spoiler log zone links against entity_mapping pairs:
- For each zone_link (A → B), check if there's a matching (B → A) in entity_mapping
- Flag inconsistencies between spoiler log and EMEVD data

**3. One-Way Link Detection**

If a dest_entity has no corresponding reverse entry (where its source_entity is another entry's dest_entity), the connection is likely one-way.

## Precision Summary

| Strategy | Precision | When Available |
|----------|-----------|----------------|
| Col-based (play_region_id) | ~95% | When mod sends play_region_id |
| Source zone prioritization | ~93% | When mod has cached zone info |
| Entity mapping + key matching | ~92% | Launcher with EMEVD parsing |
| Preexisting-adjacent fallback | ~88% | When mod's source has preexisting neighbors |
| Key matching only | ~82% | Spoiler log with fog.txt enrichment |
| Position rules (submaps.txt) | ~70% | Always (fallback) |
| Sibling map fallback | ~65% | When map has no direct zones |
| Display name matching | ~60% | Always (last resort) |

## Resolution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Mod Discovery Event                                         │
│ map_id, position, play_region_id, destination_entity_id,   │
│ source_zone_id                                              │
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
            │   Source zone from mod matches?     │
            └─────────────────┬───────────────────┘
                    Yes ┌─────┴─────┐ No
                        ▼           │
              ┌─────────────────┐   │
              │ Filter to mod's │   │
              │ source zone     │   │
              │ (AUTHORITATIVE) │   │
              └────────┬────────┘   │
                       └─────┬──────┘
                             ▼
            ┌─────────────────────────────────────┐
            │   Entity mapping available?         │
            └─────────────────┬───────────────────┘
                    Yes ┌─────┴─────┐ No
                        ▼           │
              ┌─────────────────┐   │
              │ Prepare expanded│   │
              │ candidates      │   │
              │ (for fallback)  │   │
              └────────┬────────┘   │
                       └─────┬──────┘
                             ▼
            ┌────────────────────────────────────┐
            │   Try key-based matching           │
            │   (position-based candidates)      │
            └─────────────────┬──────────────────┘
                    Found ┌───┴───┐ Not found
                          ▼       │
              ┌───────────────┐   │
              │ Return match  │   │
              └───────────────┘   │
                                  ▼
            ┌────────────────────────────────────┐
            │   Fallback 1: Source expansion     │
            │   (entity mapping, if authoritative)│
            └─────────────────┬──────────────────┘
                    Found ┌───┴───┐ Not found
                          ▼       │
              ┌───────────────┐   │
              │ Return match  │   │
              │ (+ warning)   │   │
              └───────────────┘   │
                                  ▼
            ┌────────────────────────────────────┐
            │   Fallback 2: Preexisting-adjacent │
            │   source expansion                 │
            └─────────────────┬──────────────────┘
                    Found ┌───┴───┐ Not found
                          ▼       │
              ┌───────────────┐   │
              │ Return match  │   │
              │ (+ warning)   │   │
              └───────────────┘   │
                                  ▼
            ┌────────────────────────────────────┐
            │   Fallback 3: Target expansion     │
            │   (if expanded != original)        │
            └─────────────────┬──────────────────┘
                    Found ┌───┴───┐ Not found
                          ▼       ▼
              ┌───────────────┐ ┌───────────────────┐
              │ Return match  │ │ Log failure and   │
              │ (+ warning)   │ │ skip discovery    │
              └───────────────┘ └───────────────────┘
```

## Troubleshooting

### Discovery Not Matching

1. **Check zone_links**: Does the game have the expected connection?
2. **Check enrichment**: Are `source_id`/`target_id` populated?
3. **Check entity_mapping**: If launcher was used, is the entity in the mapping?
4. **Check logs**: Server logs show resolution attempts with candidates

### Multiple Matches

If multiple zone links match the same candidates:
- Server picks the first match in spoiler log order
- This can lead to incorrect matches in rare cases
- Entity mapping helps by narrowing candidates

### Destination Zone Display (Re-Traversing)

When the player re-traverses an already-discovered fog gate where multiple matches exist:

**Problem**: If both a `preexisting` link and a `random` link match the same source/target candidates, the in-game display might show the wrong destination zone. For example, traversing a randomized fog gate to "Limgrave Tunnels - Stonedigger Troll" could incorrectly display "Limgrave" if a preexisting link also connects those zones.

**Solution**: When selecting the destination zone for display:
1. If new links were discovered, use the primary discovery result's target
2. If re-traversing (no new links), prefer `random` type links over `preexisting`

```
┌─────────────────────────────────────────────────────────────┐
│ Player traverses fog gate from Caelid                        │
│ Matches found:                                               │
│   - caelid → limgrave (preexisting) - already discovered    │
│   - caelid → limgrave_tunnels_boss (random) - already disc. │
│                                                              │
│ No new links discovered (re-traversing)                      │
│                                                              │
│ Destination zone selection:                                  │
│   1. Check for random link → found limgrave_tunnels_boss    │
│   2. Display: "Limgrave Tunnels - Stonedigger Troll" ✓      │
└─────────────────────────────────────────────────────────────┘
```

**Why random links are preferred**: The player traversed a randomized fog gate, so the destination should be the randomized connection's target, not a vanilla (preexisting) connection that happens to exist between the same zones.

### Missing Zone Keys

If enrichment fails:
- Check if zone display name is in fog.txt
- Check if detail text matches ASide/BSide entries
- Manual zone_key addition may be needed for edge cases

### Zone Not in Candidates (Map Mismatch)

If the target zone exists but isn't found in candidates:
1. Check the map_id reported by the mod (in server logs)
2. Compare with the `Maps:` field in fog.txt for that zone
3. If the mod reports a different map, the zone may still be found via ASide/BSide resolution (see below)

#### ASide/BSide Zone Resolution

Zones referenced in fog gate `ASide:` or `BSide:` entries are automatically added as candidates for the fog gate's map. This handles cases where:

- **Dungeon exits**: A fog gate in dungeon A leads to a zone physically in area B
- **Cross-map connections**: The spoiler log names a zone by its logical destination, not the fog gate's physical map

**Example**: Academy Crystal Cave (m31_06_00_00) has fog gate 31061801:
```yaml
- Name: AEG099_001_9001
  ID: 31061801
  Area: m31_06_00_00
  ASide:
    Area: academy_cavetower  # Physically in m14_00_00_00
  BSide:
    Area: liurnia_academycave_boss
```

Even though `academy_cavetower` has `Maps: m14_00_00_00`, it becomes a candidate for `m31_06_00_00` because the fog gate's ASide references it. This enables matching when the spoiler log says a randomized fog gate leads to "Academy of Raya Lucaria - After Academy Crystal Cave".

#### Manual Map Addition (Fallback)

If ASide/BSide resolution doesn't apply (no fog gate references the zone), add the map manually:

```yaml
# Before
- Name: shadowkeep
  Text: Shadow Keep
  Maps: m21_00_00_00

# After (add the map reported by mod)
- Name: shadowkeep
  Text: Shadow Keep
  Maps: m21_00_00_00 m21_01_00_00
```

**Note**: The `Maps:` field represents the zone's **physical location**. Only add maps where the zone actually exists. For cross-map fog gate connections, rely on ASide/BSide resolution instead.

**Note**: The sibling fallback only helps when the map has NO zones. If the map has other zones but not the target, check ASide/BSide resolution first.

### Duplicate Display Names

If two zones share the same display name, `lookup_by_display_name` will return the **first** zone found in fog.txt. This can cause incorrect resolution.

**Prevention**: Each real zone in fog.txt should have a unique display name. A unit test (`test_no_duplicate_display_names_for_real_zones`) validates this.

**If you find duplicates**:
1. Rename one of the zones in fog.txt to have a distinct name
2. Update graces.json if any graces reference the renamed zone
3. Run `scripts/fix_duplicate_zone_ids.py` to fix existing games

**Example fix** (from a past bug):
```yaml
# Before: Two zones with same name
- Name: sewer_mohg
  Text: Mohg, the Omen
- Name: sewer_mohg_flame
  Text: Mohg, the Omen

# After: Unique names
- Name: sewer_mohg
  Text: Mohg, the Omen
- Name: sewer_mohg_flame
  Text: Mohg, the Omen - Flame Door
```
