# Graph Model

This document describes the data model for the fog gate graph, including zones, links, discoveries, and how they're stored.

## Concepts

### Zone (Node)

A zone represents an area in Elden Ring. It's a node in the graph.

```json
{
  "id": "Limgrave - Church of Elleh",
  "isBoss": false,
  "scaling": 10,
  "isHub": false
}
```

| Field | Description |
|-------|-------------|
| `id` | Display name (unique identifier) |
| `isBoss` | True if this zone contains a boss |
| `scaling` | Enemy scaling level (higher = harder) |
| `isHub` | True if this is a hub node (3+ connections) |

### Zone Link

A zone link represents a fog gate connection between two zones.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "Limgrave - Church of Elleh",
  "source_id": "uuid-of-source-zone",
  "target": "Liurnia - Academy Gate Town",
  "target_id": "uuid-of-target-zone",
  "type": "random",
  "oneWay": false,
  "source_details": "After the boss room",
  "target_details": "Near the Site of Grace",
  "source_key": "1101_ChurchOfElleh_Exit1",
  "target_key": "1205_AcademyGateTown_Entry1"
}
```

| Field | Description |
|-------|-------------|
| `id` | UUID for this specific link |
| `source` | Source zone display name |
| `source_id` | UUID of the source zone |
| `target` | Target zone display name |
| `target_id` | UUID of the target zone |
| `type` | `random` (randomized gate) or `preexisting` (always there) |
| `oneWay` | True if link can only be traversed in one direction |
| `source_details` | Description of exit location (from spoiler log) |
| `target_details` | Description of entry location (from spoiler log) |
| `source_key` | Internal zone key for source (from fog.txt) |
| `target_key` | Internal zone key for target (from fog.txt) |

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

When you traverse A→B, both directions become usable.

### One-Way (Unidirectional)

Some connections can only be traversed in one direction:

```
Zone A ──────────► Zone B
         (no return)
```

**Detection in spoiler log**: Keywords like "(sending gate)" or "(coffin)" indicate one-way links.

**One-way triggers**:
- Sending gates (teleport with no return)
- Coffins (one-way transport)
- Some boss fog walls (enter but can't exit)

**Impact**:
- Undiscovery: Can reach A from B? Only if bidirectional
- Path finding: Can only go forward on one-way links
- Placeholder: Only created in traversable direction

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

Two discovered zones might have **multiple** fog gates between them:

```
           ┌────────────────┐
           │ Fog Gate A (?) │
Zone A ────┼────────────────┼──── Zone B
           │ Fog Gate B (✓) │
           └────────────────┘
```

Even if both zones are discovered, Gate A remains hidden until traversed.

**Result**: No spoilers about connection layout.

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
???_{fromNodeId}_{realNodeId}
```

Example: `???_Limgrave - Church of Elleh_Liurnia - Academy Gate Town`

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

**Algorithm** (recursive):
1. Mark zone as discovered
2. For each preexisting link from this zone:
   - If target not discovered AND (bidirectional OR forward direction):
     - Recursively discover target
     - Mark link as discovered

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
zone_links           JSONB  -- array of zone_link objects
zones                JSONB  -- array of zone metadata (with UUIDs)
discovered_zone_links JSONB  -- array of discovered zone_link objects
node_positions       JSONB  -- {zone_id: {x, y}}
tags                 JSONB  -- {zone_id: [tag_ids]}
entity_mapping       JSONB  -- {dest_entity: {source_map, dest_map}}
```

### Client (localStorage)

```javascript
// Key: er-fog-exploration-{seed}
{
  "version": 2,
  "discovered": ["Zone A", "Zone B", ...],
  "discoveredLinks": ["uuid1", "uuid2", ...],
  "tags": {"Zone A": ["tag1", "tag2"]}
}
```

**Version history**:
- v1: `discoveredLinks` stored as `"sourceId|targetId"` strings
- v2: `discoveredLinks` stored as UUIDs (current)

Migration from v1→v2 happens automatically on load.

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

Based on scaling level:
- Low scaling (1-20): Small circle
- Medium scaling (21-80): Medium circle
- High scaling (81+): Large circle

Boss nodes have a special marker (skull icon or different shape).

## Link Index

The client maintains an index for efficient link lookups:

```javascript
{
  byId: Map<uuid, link>,           // Direct lookup by UUID
  byNodes: Map<"A|B", link[]>,     // All links between two nodes
  bySourceTarget: Map<"A→B", link> // Specific direction lookup
}
```

This enables:
- Fast check if link is discovered
- Finding all links between two nodes
- Bidirectional link handling
