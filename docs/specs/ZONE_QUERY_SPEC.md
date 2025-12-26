# Zone Query After Fast Travel

## Goal

Allow the mod to display the current zone and its exits after a fast travel (grace site teleportation), even without traversing a fog gate.

## Context

Currently, after fast travel:
1. The mod detects exiting the loading screen (`position_now_readable && !self.was_position_readable`)
2. Since there's no `pending_warp`, it clears `current_zone` and `current_exits`
3. The overlay displays nothing

## Solution

New WebSocket message `zone_query`:
```
Fast travel → loading screen → position readable → mod sends zone_query
→ server resolves zone by position → responds zone_query_ack with zone + exits
```

---

## Implementation

### 1. Server: New `zone_query` handler

**File**: `server/fogtracker/websocket/mod.py`

1. Add handler in `_register_handlers()`:
   ```python
   "zone_query": self._handle_zone_query,
   ```

2. Implement `_handle_zone_query()`:
   ```python
   async def _handle_zone_query(self, data: dict):
       """Handle zone query (after fast travel)."""
       map_id = data.get("map_id", "")
       pos = data.get("pos", {})
       play_region_id = data.get("play_region_id")

       # Resolve zone (same logic as discovery_v2)
       resolver = get_resolver()

       # Try Col first if available
       zone_internal = None
       zone_display = None
       if play_region_id:
           col = f"h{play_region_id:06x}"
           zone_internal, zone_display = resolver.resolve_by_col(map_id, col)

       # Fallback to position
       if not zone_internal:
           candidates = resolver.resolve_all_candidates(
               map_id, pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
           )
           if candidates:
               zone_internal, zone_display = candidates[0]

       if not zone_display:
           await self.send({"type": "zone_query_ack", "zone": None, "exits": []})
           return

       # Get exits
       async with async_session() as db:
           game = await get_game_by_id(db, self.game_id)
           exits = compute_zone_exits(
               game.zone_links or [],
               game.discovered_zone_links or [],
               zone_display,
           )

       await self.send({
           "type": "zone_query_ack",
           "zone": zone_display,
           "exits": exits,
       })
   ```

### 2. Mod: Send `zone_query` after fast travel

**File**: `mod/src/websocket.rs`

1. Add `ZoneQuery` to `OutgoingMessage`:
   ```rust
   ZoneQuery {
       map_id: u32,
       pos: Position,
       play_region_id: Option<u32>,
   },
   ```

2. Add `ZoneQuery` to `ServerMessage` (serialization):
   ```rust
   ZoneQuery {
       map_id: String,
       pos: Position,
       play_region_id: Option<u32>,
   },
   ```

3. Add `ZoneQueryAck` to `ServerResponse`:
   ```rust
   ZoneQueryAck {
       zone: Option<String>,
       #[serde(default)]
       exits: Vec<FogExit>,
   },
   ```

4. Add `send_zone_query()` method to `WebSocketClient`:
   ```rust
   pub fn send_zone_query(&self, map_id: u32, pos: (f32, f32, f32), play_region_id: Option<u32>) {
       if let Some(tx) = &self.tx {
           let _ = tx.try_send(OutgoingMessage::ZoneQuery {
               map_id,
               pos: Position { x: pos.0, y: pos.1, z: pos.2 },
               play_region_id,
           });
       }
   }
   ```

5. Handle `ZoneQueryAck` in `message_loop()` and `IncomingMessage`

**File**: `mod/src/tracker.rs`

6. Modify `check_fog_traversal()` - instead of just clearing the zone:
   ```rust
   if position_now_readable && !self.was_position_readable && self.pending_warp.is_none() {
       // Send zone_query instead of just clearing
       if let Some(pos) = self.game_state.read_position() {
           if self.ws_client.is_connected() {
               info!(
                   map_id = pos.map_id_str,
                   "[ZONE_QUERY] Sending after loading screen"
               );
               self.ws_client.send_zone_query(
                   pos.map_id,
                   pos.pos(),
                   pos.play_region_id,
               );
           }
       }
       // Clear temporarily while waiting for response
       self.current_zone = None;
       self.current_exits.clear();
   }
   ```

7. Handle `ZoneQueryAck` in `poll_websocket()`:
   ```rust
   IncomingMessage::ZoneQueryAck { zone, exits } => {
       info!(zone = ?zone, exit_count = exits.len(), "Zone query response");
       if zone.is_some() {
           self.current_zone = zone;
           self.current_exits = exits;
       }
   }
   ```

### 3. Documentation

**File**: `docs/PROTOCOL.md`

Add in "Mod Messages" section:

```markdown
#### Mod → Server: `zone_query`

Sent after fast travel to request current zone info.

```json
{
  "type": "zone_query",
  "map_id": "m10_01_00_00",
  "pos": {"x": 100.0, "y": 50.0, "z": 200.0},
  "play_region_id": 1048576
}
```

#### Server → Mod: `zone_query_ack`

Response with resolved zone and exits.

```json
{
  "type": "zone_query_ack",
  "zone": "Limgrave - Church of Elleh",
  "exits": [...]
}
```
```

---

## Files to modify

| File | Changes |
|------|---------|
| `server/fogtracker/websocket/mod.py` | +handler `_handle_zone_query` |
| `mod/src/websocket.rs` | +messages `ZoneQuery`, `ZoneQueryAck`, +method `send_zone_query` |
| `mod/src/tracker.rs` | Modify loading screen detection, +handle `ZoneQueryAck` |
| `docs/PROTOCOL.md` | Document new messages |

## Testing

1. **Manual test**: Fast travel to a grace site, verify overlay displays zone and exits
2. **Server unit test**: Test `_handle_zone_query` with various positions

## Risks / Notes

- **Timing**: `zone_query` is sent as soon as position becomes readable. If server response is slow, overlay will be empty briefly (acceptable).
- **Unresolved zone**: If position doesn't match any zone, server returns `zone: null` and overlay stays empty (current behavior).

## Optimization: Conservative Zone Filtering

Since a player can only fast travel to a grace site in a zone they've discovered, we use this to improve zone resolution accuracy with a conservative approach:

| Situation | Result |
|-----------|--------|
| Col resolves to discovered zone | ✅ Return zone |
| Col resolves to undiscovered zone | Try position fallback |
| Position → exactly 1 discovered candidate | ✅ Return zone |
| Position → 0 or >1 discovered candidates | ❌ Return null |

**Rationale**: Better to show nothing than to show incorrect zone info that could mislead the player. Col resolution is precise (play_region_id is unique), so we trust it if the zone is discovered. Position-based resolution can match multiple overlapping zones, so we only return a result when there's no ambiguity.
