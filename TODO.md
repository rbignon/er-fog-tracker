# TODO

## 1. Fix one-way path handling (especially on pre-existing links)

**Problem**: One-way links on pre-existing connections are not handled correctly.

**Investigation needed**:
- Review `computeOneWayLinks()` in `web/js/exploration.js` - how are pre-existing links marked as one-way?
- Check `propagatePreexistingDiscoveries()` - does it respect one-way direction?
- Verify the spoiler log parser correctly identifies one-way pre-existing links

**Possible fixes**:
- Option A: Pre-existing links should inherit one-way status from the fog gate they replace
- Option B: Pre-existing links might need separate one-way metadata in the spoiler log
- Option C: The graph data structure might need a `preexistingOneWay` flag distinct from `oneWay`

**Files to check**: `web/js/exploration.js`, `web/js/parser.js`, `web/js/graph.js`

---

## 2. Handle teleporter and "return to entrance" flags (not just fog gates)

**Problem**: The mod currently only tracks fog gate transitions. Teleporters and "return to entrance" prompts also change zones.

**Implementation approach**:
- In the Rust mod, hook additional game events:
  - Teleporter activation (e.g., Waygate teleporters, coffin rides)
  - "Return to entrance" menu option
  - Potentially: death respawn, trap chests
- Send the same zone change event to the server with a `transitionType` field

**Investigation needed**:
- Find memory addresses/hooks for teleporter events in Elden Ring
- Determine if teleporters have unique IDs that map to fog gate randomizer entries
- Check if "return to entrance" has a consistent hook point

**Files to modify**: `mod/src/` (Rust hooks), `server/fogtracker/api/` (handle new event types)

---

## 3. Map grace site teleportation to fog randomizer areas

**Problem**: When the player teleports to a grace, we should detect the destination area.

**Investigation needed**:
- Find the game event for grace teleportation (menu selection → loading → spawn)
- Determine how graces are identified (grace ID? map ID? coordinates?)
- Build a mapping table: `grace_id → area_id` for fog randomizer zones

**Implementation options**:
- Option A: Hook the grace teleport event, extract destination grace ID, lookup area
- Option B: Detect zone change after grace teleport and use the new zone ID
- Option C: Monitor player position after teleport and match to known area bounds

**Data needed**: A complete list of grace sites with their zone associations. This might exist in fog randomizer data files or need to be extracted from game data.

**Files to create/modify**: `mod/src/graces.rs` (mapping table), mod hooks for grace teleport

---

## 4. Fix Roundtable Hold fog gate issue

**Problem**: The Roundtable Hold fog gate has a specific bug (details unclear).

**Investigation needed**:
- What exactly is the bug? (Wrong area detection? Missing connection? Visual glitch?)
- Roundtable Hold is special: it's accessed via grace menu, not fog gate
- Check how fog randomizer handles Roundtable (it might have multiple entry points)

**Possible issues**:
- Roundtable might not have a fog gate in the randomizer
- The area ID might be detected incorrectly
- Transitions to/from Roundtable might not trigger properly

**Files to check**: Spoiler log format for Roundtable, `web/js/parser.js` for area ID handling

---

## 5. Display kill count and timer on in-game overlay

**Context**: This is for the ImGui overlay rendered by the Rust mod, not the website.

**Implementation plan**:
1. **Kill tracking**:
   - Hook enemy death events in the game
   - Filter to count only meaningful enemies (not critters)
   - Store count in mod state

2. **Timer**:
   - Start on game load or first fog transition
   - Pause on menu/loading screens (optional)
   - Display as `HH:MM:SS`

3. **ImGui rendering**:
   - Add stats line to existing overlay: `Kills: 123 | Time: 01:23:45`
   - Position configurable (top-left, top-right, etc.)

**Investigation needed**:
- Find memory addresses for enemy death events
- Determine how to distinguish enemy types (boss vs mob vs critter)

**Files to modify**: `mod/src/tracker.rs` (data collection), `mod/src/overlay.rs` (ImGui rendering)

---

## 6. Display more stats on in-game overlay

**Context**: Additional statistics for the ImGui overlay in the Rust mod.

**Ideas for stats to track**:
- Deaths count (hook player death event)
- Areas discovered (X / total from spoiler log)
- Fog gates traversed (already tracked)
- Bosses defeated (hook boss death, need boss ID list)
- Current runes (read from memory)
- Session vs total playtime

**Implementation**: Add fields to mod state, update on relevant game events, render in ImGui.

**Considerations**:
- Make stats toggleable (user might want minimal display)
- Consider a "detailed stats" view vs "minimal" view
- Sync some stats to server for website display (optional)

---

## 7. Fix incorrect interchange display for pass-through nodes

**Problem**: Nodes with only 1 entrance and 1 exit are displayed as interchanges (hubs) on the graph.

**Investigation needed**:
- How is `isHub` computed? Check `web/js/graph.js` or `web/js/parser.js`
- Current logic likely counts total connections regardless of direction
- A node with 2 connections (1 in, 1 out) should NOT be a hub

**Correct logic**:
```javascript
// A hub should have 3+ meaningful routing choices
const isHub = (node) => {
  const connections = getNodeConnections(node.id);
  // Count unique destinations (not just link count)
  return connections.length >= 3;
};
```

**Edge cases to consider**:
- One-way links (entry-only or exit-only)
- Pre-existing links vs randomized links
- Bidirectional single links (count as 1 or 2?)

**Files to check**: `web/js/parser.js` (hub detection), `web/js/graph.js` (rendering)

---

## 8. Show mod connection status on website (host mode)

**Implementation plan**:

1. **Connection indicator**:
   - Add a status icon/button in the host UI: "Mod: Connected" / "Mod: Disconnected"
   - Green dot = connected, red dot = disconnected
   - Pulse animation when receiving data

2. **Configuration popup**:
   - Click the status button to open mod config modal
   - Show: Mod version, connection IP/port, last event received
   - Allow: Reconnect, change port, view logs

3. **Backend changes**:
   - Track which sessions have an active mod connection
   - Send `modConnected` / `modDisconnected` events to host

**Files to modify**:
- `server/fogtracker/api/` - track mod connections per session
- `web/js/sync.js` - handle mod status events
- `web/js/ui.js` - status indicator and config modal

---

## 9. Create game session directly from in-game mod

**Goal**: Instead of uploading spoiler log on website, configure the mod with the spoiler log path and let it create the session.

**Implementation plan**:

1. **Mod configuration**:
   - Add config file or in-game menu: `spoiler_log_path = "C:\path\to\FogGateRandomizer\spoiler_logs\"`
   - Mod reads and parses the spoiler log on game start

2. **Session creation flow**:
   - Mod connects to server with `POST /api/sessions/create` + spoiler log data
   - Server creates session and returns session code
   - Mod receives code, can display it in overlay for stream viewers
   - Player opens website with `?viewer=true&session=CODE` to see the map

**Files to create/modify**:
- `mod/src/config.rs` - configuration handling
- `mod/src/spoiler.rs` - spoiler log parsing (port from JS or use existing Rust parser)
- `server/fogtracker/api/sessions.py` - endpoint for mod-initiated session creation

---

## 10. Show required key items for exits in overlay

**Context**: Some fog gates require key items (e.g., Stonesword Keys, specific quest items). The overlay should indicate this.

**Implementation**:
- Parse `requiredItemFrom` field from spoiler log zone pairs
- In contextual view, display requirement next to the exit:
  ```
  [3] → ??? (undiscovered)
        From: sealed door near grace
        🔑 Requires: Stonesword Key (x2)
  ```
- Visual indicator (🔑 icon or colored text) for locked exits

**Data source**: The `requiredItemFrom` field in zone pairs already contains this info.

**Files to modify**: `mod/src/overlay.rs` (display), zone pairs parsing

---

## 11. Global frontier view in overlay

**Goal**: A view showing ALL accessible undiscovered fogs across the entire game, grouped by source zone.

**Design** (toggle with Tab from contextual view):
```
🌐 GLOBAL FRONTIER                    12 fogs available

FROM: Chapel of Anticipation
────────────────────────────
  [1] → Mt. Gelmir - Gelmir Hero's Grave
        before Grafted Scion's arena
  [2] → Stormveil Castle after Gate
        before Grafted Scion's arena

FROM: Farum Azula - Dragon Temple
────────────────────────────
  [3] → ??? (undiscovered)
        before back left of Godskin Duo arena
...
```

**Implementation**:
- Compute frontier from discovered zones + zone pairs
- Group by source zone
- Scrollable list for large frontiers
- Number shortcuts (1-9) to focus on map

**Files to modify**: `mod/src/overlay.rs`, `mod/src/exploration.rs` (frontier computation)

---

## 12. Keyboard shortcuts in overlay

**Goal**: Quick navigation and actions without mouse.

**Shortcuts**:
| Key | Action |
|-----|--------|
| `H` | Toggle overlay visibility |
| `Tab` | Switch contextual ↔ global view |
| `1-9` | Select exit by number → site zooms to that node |
| `↑↓` | Navigate list (in global view) |
| `Enter` | Confirm selection |
| `T` | Open tag menu |
| `T + 1-6` | Quick tag current zone |

**Implementation**:
- Hook keyboard input in mod
- Send `focus_node` WebSocket message when selecting an exit
- ImGui handles list navigation

**Files to modify**: `mod/src/input.rs` (keyboard hooks), `mod/src/overlay.rs` (shortcut handling)

---

## 13. Bidirectional sync between overlay and website

**Goal**: Actions in overlay reflect on site and vice-versa.

**Overlay → Site**:
- Select fog [3] in overlay → site zooms to that node and highlights it
- Add tag in overlay → tag appears on site immediately

**Site → Overlay** (optional, lower priority):
- Select node on site → overlay shows that zone's exits
- Add tag on site → tag appears in overlay

**Implementation**:
- New WebSocket message types: `focus_node`, `tag_added`, `tag_removed`
- Site listens for `focus_node` and animates zoom to target
- Overlay listens for tag changes and updates display

**Files to modify**:
- `mod/src/server_client.rs` - send/receive sync messages
- `web/js/sync.js` - handle `focus_node` messages
- `web/js/graph.js` - zoom animation to node

---

## 14. Offline queue for discoveries

**Problem**: If server is unreachable, discoveries are lost.

**Solution**: Queue discoveries locally and send them when connection is restored.

**Implementation**:
1. On discovery, try to send via WebSocket
2. If send fails or no connection, store in local queue (in memory or file)
3. On reconnect, replay queued discoveries in order
4. Clear queue after successful send

**Edge cases**:
- Game closed before reconnect → persist queue to file
- Server rejects duplicate discovery → ignore (already recorded)
- Queue grows too large → cap at N entries, warn user

**Files to modify**: `mod/src/server_client.rs` (queue logic), `mod/src/config.rs` (persistence path)
