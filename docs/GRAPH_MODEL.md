# Graph Model

This document describes the data model for the fog gate graph, including zones, links, discoveries, and how they're stored.

> **Note:** This document uses the **API format (snake_case)**. The frontend transforms these to camelCase via `web/js/api.js` (e.g., `is_boss` → `isBoss`, `source_id` → `sourceId`).

## Concepts

### Zone (Node)

A zone represents an area in Elden Ring. It's a node in the graph.

```json
{
  "id": "limgrave_church_of_elleh",
  "name": "Limgrave - Church of Elleh",
  "is_boss": false,
  "scaling": "tier 1, previously 6"
}
```

| Field | Description |
|-------|-------------|
| `id` | Zone key (internal identifier from fog.txt, e.g., "limgrave_stormhill") |
| `name` | Display name of the zone |
| `is_boss` | True if this zone contains a boss (detected via `<<<<<` in spoiler log) |
| `scaling` | Scaling info from spoiler log (text field, e.g., "tier 1, previously 6") |

> **Frontend note:** The `id` field is the zone key (used for D3.js bindings and lookups), while `name` is for display. The frontend computes `isHub` dynamically (true if zone has 3+ distinct connections).

### Zone Link

A zone link represents a fog gate connection between two zones.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "Limgrave - Church of Elleh",
  "source_id": "limgrave_church_of_elleh",
  "target": "Liurnia - Academy Gate Town",
  "target_id": "liurnia_academy_gate_town",
  "type": "random",
  "is_one_way": false,
  "blocks_propagation": false,
  "source_details": "After the boss room",
  "target_details": "Near the Site of Grace",
  "required_item": "Academy Glintstone Key",
  "required_item_from": "Liurnia - Behind Caria Manor;Liurnia - Temple Quarter"
}
```

| Field | Description |
|-------|-------------|
| `id` | UUID for this specific link |
| `source` | Source zone display name |
| `source_id` | Source zone key (from fog.txt) |
| `target` | Target zone display name |
| `target_id` | Target zone key (from fog.txt) |
| `type` | `random` (randomized gate) or `preexisting` (always there) |
| `is_one_way` | True if link can only be traversed in one direction (hides reverse exit) |
| `blocks_propagation` | True if traversing this link should not propagate preexisting links from destination |
| `source_details` | Description of exit location (from spoiler log) |
| `target_details` | Description of entry location (from spoiler log) |
| `required_item` | Key item required to traverse this link (optional) |
| `required_item_from` | Semicolon-separated list of zones where the required item can be found (optional) |

## Link Types

### Random Links

Fog gates that have been randomized by FogMod. The target is different from vanilla.

- **Source**: Where the fog gate is located
- **Target**: Where it leads (randomized)
- Drawn as **orange** lines in the graph

### Preexisting Links

Connections that exist in vanilla Elden Ring (no fog gate required).

Examples:
- Doors between areas
- Elevators
- Ladder connections
- Open passages

- Always bidirectional (unless explicitly one-way)
- Drawn as **gray dashed** lines
- **Auto-propagation**: Discovering one side discovers the whole preexisting group

## One-Way vs Two-Way

### Two-Way (Bidirectional)

Most fog gates can be traversed in both directions:

```
Zone A ◄─────────► Zone B
```

When you traverse A→B, both directions become usable. This is the default for all link types (random and preexisting).

### One-Way (Unidirectional)

Some connections can only be traversed in one direction:

```
Zone A ──────────► Zone B
         (no return)
```

**Detection in spoiler log**: The `is_one_way` field is set to `true` when keywords like "(sending gate)", "(coffin)", or "(dropping)" are detected in the spoiler log.

**One-way triggers**:
- Sending gates (teleport with no return)
- Coffins (one-way transport)
- Drop-downs (can't climb back up)
- Some boss fog walls (enter but can't exit)

**Unified logic**: Both random and preexisting links use the same `is_one_way` field. A link is bidirectional unless explicitly marked as one-way. The absence of a reverse link does NOT imply one-way (doors and elevators are bidirectional even without explicit reverse entries).

**Impact**:
- Undiscovery: Can reach A from B? Only if bidirectional
- Path finding: Can only go forward on one-way links
- Placeholder: Only created in traversable direction

### Conditional Links (blocks_propagation)

Some fog gates have physical barriers (shortcut ladders, one-way doors) that prevent full access to the destination zone without meeting a condition. These are detected via `Cond:` fields in fog.txt.

```
Zone A ◄────────────► Zone B
  (ladder not deployed)   │
                          │ preexisting links
                          ▼ NOT propagated
                       Zone C
```

**Example**: The fog gate at Queen's Bedchamber (shortcut ladder) leads to a catacombs boss room. The player can:
- See and use the "return to entrance" exit from the boss room
- But NOT access the rest of Bedchamber (ladder not deployed from their side)

**Difference from `is_one_way`**:
- `is_one_way=true`: Hides the reverse exit (player can't see it in exits list)
- `blocks_propagation=true`: Shows the reverse exit, but doesn't propagate preexisting links from destination

**Why this matters**: Without `blocks_propagation`, traversing the link would reveal all preexisting links from Bedchamber (Gideon's arena, rooftop connections), even though the player can't actually reach them.

## Discovered Zone Links

When a player traverses a fog gate, the specific link is marked as discovered.

```json
{
  "zone_link_id": "550e8400-e29b-41d4-a716-446655440000",
  "discovered_at": "2024-01-15T10:30:00Z",
  "discovered_by": "mod"
}
```

| Field | Description |
|-------|-------------|
| `zone_link_id` | UUID of the zone_link |
| `discovered_at` | ISO timestamp of discovery |
| `discovered_by` | `mod` (in-game) or `web` (manual) |

### Why Track Links, Not Just Nodes?

Two discovered zones might have **multiple** fog gates between them (parallel links):

```
           ┌────────────────┐
           │ Fog Gate A     │
Zone A ────┼────────────────┼──── Zone B
           │ Fog Gate B     │
           └────────────────┘
```

**Parallel Links Behavior**: When discovering any link between two zones, ALL parallel links between those same zones are discovered together. This is because:

1. The mod cannot distinguish which specific fog gate was traversed (entity IDs map to the same source/target maps)
2. The in-game display already shows all exits to a zone as discovered if any link exists
3. From the player's perspective, they've "found the connection" between zones A and B

**Example**: Divine Tower of Caelid has 3 entrances from Dragonbarrow:
- Middle entrance (link-1)
- Right entrance (link-2)
- Left entrance (link-3, leads to boss arena)

When traversing any entrance to the tower, links 1 and 2 are both discovered (same `target_id: caelid_tower`). Link 3 goes to a different zone (`target_id: caelid_tower_boss`) so it remains undiscovered.

**Note**: Links to different target zones are NOT auto-discovered, only links with identical `source_id` AND `target_id`.

## Placeholder Nodes (???)

In exploration mode, undiscovered connections are shown as placeholder nodes.

### Placeholder for Undiscovered Node

```
Zone A (discovered) ──► ??? (placeholder for Zone B)
```

The placeholder hides what's behind it. Clicking reveals Zone B.

### Placeholder for Undiscovered Link

If both endpoints are discovered but the link hasn't been traversed:

```
Zone A (discovered) ──► ??? ──► Zone B (discovered)
```

**Key insight**: The user can't tell if ??? leads to a new area or loops back to somewhere known. This preserves the exploration surprise.

### Placeholder ID Format

```
???_{fromZoneId}_{realZoneId}
```

Example: `???_limgrave_church_of_elleh_liurnia_academy_gate_town`

Where `fromZoneId` and `realZoneId` are zone keys (not display names).

### Placeholder Positioning

Placeholders are positioned near their source node with a deterministic offset based on a hash of the ID. This ensures consistent positioning across sessions.

## Discovery Propagation

### Preexisting Propagation

When discovering a zone, all preexisting connections are automatically traversed:

```
       random                preexisting              preexisting
Zone A ─────► Zone B ◄───────────────────► Zone C ◄─────────────► Zone D
       (fog)              (door)                    (elevator)

Discover B → Also discovers C and D (via preexisting links)
```

**Algorithm** (recursive BFS):
1. Queue the newly discovered link (source → target)
2. While queue is not empty:
   - Process link (src → dst)
   - If dst is a newly discovered node:
     - Queue all preexisting links from dst
   - Else if dst was already reachable (via preexisting from another zone):
     - **Still queue preexisting links from dst** (ensures they're explicitly recorded)
   - Mark link as discovered

**Important**: Preexisting links are propagated even when the target zone was already
in `discovered_nodes` (reachable via preexisting expansion). This ensures that:
- All preexisting links are explicitly recorded in `discovered_zone_links`
- Exits are correctly displayed in the UI

**Example** (Castle Sol scenario):
```
                random                     preexisting                 preexisting
Siofra River ─────────► Mountaintops ◄───────────────────► Castle Sol ◄─────────────► Flame Peak
                           (discovered)                      (reachable)               (reachable)

1. Siofra → Mountaintops discovered
   → Castle Sol becomes reachable (in discovered_nodes via preexisting)

2. Later: Catacombs Boss → Castle Sol discovered
   → Castle Sol was already reachable, but preexisting links NOT recorded
   → Now: Castle Sol → Mountaintops and Mountaintops → Flame Peak are propagated
```

### Parallel Links Propagation

When discovering a link between zones A and B, ALL links with the same `source_id` and `target_id` are discovered together:

```
           ┌─ Fog Gate 1 (middle entrance) ─┐
           │                                │
Dragonbarrow ─ Fog Gate 2 (right entrance) ─── Divine Tower of Caelid
           │                                │
           └────────────────────────────────┘

Traverse any entrance → Both links discovered
```

**Algorithm**:
1. Find all zone links where (`source_id`, `target_id`) matches (either direction)
2. For each link not already discovered:
   - Mark link as discovered
   - First link goes to `main_links`, others to `forward_links` in the result

**Why**: The mod cannot distinguish which specific fog gate was traversed when multiple gates connect the same two zones (they have identical source/target maps in the entity mapping).

### Back-Propagation

When discovering a zone that's not reachable from the starting area:

```
                   ┌─────────────────────────────────┐
                   │                                 │
START ──► A ──► B  │  C ──► D ◄── (current position) │
          │        │  ▲                              │
          └────────┼──┘                              │
                   │                                 │
                   └─────────────────────────────────┘

Player is at D (not discovered), discovers C
→ Path START→A→C is discovered first (back-propagation)
→ Then C→D is discovered
```

**Why**: The graph must remain connected to the starting area.

**Bidirectional link optimization**: For bidirectional links (`is_one_way: false`), back-propagation is skipped if the **target** is already accessible from START. In this case, the source will become accessible via the bidirectional link itself:

```
                              bidirectional
START ──► ... ──► Target ◄────────────────────► Source
          (accessible)                        (not yet accessible)

Discover Source→Target (bidirectional link)
→ NO back-propagation needed
→ Source is now accessible via the link to Target
```

**One-way links** (`is_one_way: true`) always trigger back-propagation when the source is not accessible, because you cannot traverse a one-way link backwards to reach the source from the target.

## Undiscovery Cascade

When undiscovering a zone, all zones that become unreachable from START are also undiscovered.

```
START ──► A ──► B ──► C ──► D
              │
              └──► E

Undiscover B → Also undiscovers C, D, E (unreachable from START)
```

**Algorithm**:
1. Undiscover the target zone and its links
2. Find all zones reachable from START (via discovered links, respecting one-way)
3. Undiscover any zones not in the reachable set

**Note**: START_NODE (Chapel of Anticipation) cannot be undiscovered.

## Storage Format

### Server (PostgreSQL)

```sql
-- games table
zone_links           JSONB  -- array of {id, source, source_id, target, target_id, type, ...}
zones                JSONB  -- object keyed by zone_id (zone_key) with zone metadata values
discovered_zone_links JSONB  -- array of {zone_link_id, discovered_at, discovered_by}
node_positions       JSONB  -- {zone_id: {x, y}} (keyed by zone_key)
tags                 JSONB  -- {zone_id: [tag_ids]} (keyed by zone_key)
starting_zone_id     VARCHAR(100)  -- zone_key of starting zone
entity_mapping       JSONB  -- {dest_entity: {source_map, dest_map}}
```

**Note**: `discovered_zone_links` stores only `zone_link_id` references. The client resolves `source`/`target` from its local `linkIndex` (built from `zone_links`).

### Client (localStorage)

```javascript
// Key: er-fog-exploration-{seed}
{
  "version": 3,
  "discovered": ["limgrave", "stormveil", ...],
  "discoveredLinks": ["uuid1", "uuid2", ...],
  "tags": {"limgrave": ["tag1", "tag2"]}
}
```

**Version history**:
- v1: `discoveredLinks` stored as `"sourceId|targetId"` strings
- v2: `discoveredLinks` stored as UUIDs, `discovered`/`tags` keyed by display name
- v3: `discovered`/`tags` keyed by zone_key (current)

Migration from v2→v3 happens automatically on load (requires zone data to map display names to zone keys).

## Graph Rendering

The graph is rendered using D3.js force simulation.

### Node Rendering

| State | Appearance |
|-------|------------|
| Discovered | Full opacity, selectable |
| Placeholder | "???" label, dashed outline |
| Highlighted | Yellow glow |
| Dimmed | 30% opacity |
| Frontier | Blue border (adjacent to discovered) |
| Access | Green border (can reach from here) |

### Link Rendering

| Type | Appearance |
|------|------------|
| Random | Orange solid line |
| Preexisting | Gray dashed line |
| One-way | Arrow at target end |
| Undiscovered | Hidden (replaced by placeholder) |

### Node Sizing

Node size is based on `is_boss`:
- Regular nodes: 7px radius
- Boss nodes: 10px radius

Boss nodes also have a distinct color (CSS class `boss`).

## Link Index

The client maintains an index for efficient link lookups (built in `web/js/state.js`):

```javascript
{
  byId: Map<linkId, link>,                    // Direct lookup by UUID
  byEndpoints: Map<"source_id|target_id", linkId[]>  // All link IDs between two nodes
}
```

For bidirectional links (`is_one_way: false`), both directions are indexed in `byEndpoints` (e.g., both `"limgrave|stormveil"` and `"stormveil|limgrave"` point to the same link ID).

This enables:
- Fast check if link is discovered (`byId.get(linkId)`)
- Finding all links between two nodes (`byEndpoints.get("limgrave|stormveil")`)
- Resolving link IDs to full link objects
