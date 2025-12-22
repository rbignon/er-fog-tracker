# Frontend Evolution Specification

This document describes the frontend changes needed to integrate with the new backend.

## 1. Overview

### 1.1 Goals

- Integrate with backend (PostgreSQL, Twitch OAuth, server-side propagation)
- Keep offline mode working (backwards compatibility)
- Support mod-driven discoveries via WebSocket
- Maintain viewer counter for OBS overlay

### 1.2 Key Changes

| Aspect | Current | Target |
|--------|---------|--------|
| Source of truth | localStorage | Server (PostgreSQL) |
| Session ID | 4-letter code | UUID game_id |
| Auth | None | Twitch OAuth |
| Discovery source | Manual clicks | Mod + manual clicks |
| Propagation | Client-side | Server-side |
| URLs | `?viewer=true&session=CODE` | `/watch/{username}/{gameId}` |
| Routing | None (single page) | History API |

### 1.3 URL Structure

```
/                           → Landing page (login button)
/dashboard                  → User's games list (auth required)
/play/{gameId}              → Host view (auth required, owner only)
/watch/{username}           → User's public games list
/watch/{username}/{gameId}  → Viewer mode (public)
/?offline=true              → Offline mode (legacy, localStorage)
```

## 2. New File Structure

```
web/js/
├── main.js                 # Entry point (updated)
├── router.js               # NEW: Client-side routing
├── auth.js                 # NEW: Auth state & helpers
├── api.js                  # NEW: REST API client
├── state.js                # Updated: backend integration
├── sync.js                 # Updated: new WebSocket protocol
├── exploration.js          # Updated: server-side propagation
├── graph.js                # Minimal changes
├── ui.js                   # Updated: new UI elements
├── parser.js               # No changes
├── toast.js                # No changes
└── pages/
    ├── landing.js          # NEW: Landing page logic
    ├── dashboard.js        # NEW: Dashboard page logic
    └── viewer-list.js      # NEW: Public user games list
```

## 3. Router (router.js)

Simple History API router.

```javascript
// Route definitions
const routes = [
  { path: '/', handler: showLanding },
  { path: '/dashboard', handler: showDashboard, auth: true },
  { path: '/play/:gameId', handler: showPlay, auth: true },
  { path: '/watch/:username', handler: showUserGames },
  { path: '/watch/:username/:gameId', handler: showViewer },
];

// API
Router.navigate('/dashboard');
Router.init();
```

### 3.1 Route Handlers

Each handler:
1. Updates DOM (show/hide sections)
2. Loads required data
3. Initializes page-specific logic

### 3.2 Auth Guard

Routes with `auth: true`:
- Check if token exists in localStorage
- If not, redirect to `/` with return URL stored

## 4. Auth (auth.js)

```javascript
// State
let apiToken = localStorage.getItem('api_token');
let currentUser = null;

// API
Auth.isAuthenticated()      // → boolean
Auth.getToken()             // → string | null
Auth.getUser()              // → { id, username, displayName } | null
Auth.login()                // → redirect to /auth/twitch
Auth.logout()               // → clear token, redirect to /
Auth.handleCallback(token)  // → store token, fetch user, redirect

// Headers helper
Auth.getHeaders()           // → { 'Authorization': 'Bearer xxx' }
```

### 4.1 Login Flow

1. User clicks "Login with Twitch"
2. Redirect to `/auth/twitch`
3. Server redirects to Twitch OAuth
4. Twitch redirects back to `/auth/twitch/callback`
5. Server redirects to `/dashboard?token=xxx`
6. Frontend extracts token from URL, stores in localStorage
7. Frontend fetches `/api/me` to get user info
8. Frontend navigates to `/dashboard`

## 5. API Client (api.js)

```javascript
// Games
Api.createGame({ seed, runId, label, zonePairs })  // → { gameId, created }
Api.getGame(gameId)                                 // → GameFull
Api.getMyGames()                                    // → { games: [...] }
Api.deleteGame(gameId)                              // → void
Api.updateGame(gameId, { label })                   // → GameSummary

// Users
Api.getUser(username)                               // → { username, displayName }
Api.getUserGames(username)                          // → { games: [...] }

// Discovery (REST fallback, prefer WebSocket)
Api.createDiscovery(gameId, { source, target })     // → { propagated: [...] }
```

## 6. State Changes (state.js)

### 6.1 New State Fields

```javascript
state = {
  // ... existing fields ...

  // Backend mode
  backendMode: 'offline' | 'online',
  gameId: null,           // UUID when online

  // Auth (reference to auth.js)
  // Not duplicated here, use Auth.isAuthenticated()
}
```

### 6.2 Backend Abstraction

State module delegates persistence based on `backendMode`:

```javascript
// When discovering
if (State.getBackendMode() === 'online') {
  // Server handles propagation, we just apply result
  const { propagated } = await Api.createDiscovery(gameId, { source, target });
  applyPropagatedDiscoveries(propagated);
} else {
  // Local propagation (existing logic)
  discoverWithPreexisting(areaId, fromNodeId, viaLink);
  saveToLocalStorage();
}
```

### 6.3 Events

New events:
- `backendModeChanged` - Switched between offline/online
- `gameLoaded` - Game loaded from server
- `modDiscovery` - Mod discovered something (via WebSocket)

## 7. Sync Changes (sync.js)

### 7.1 New WebSocket Protocol

**Host Connection:**
```javascript
// Connect
ws = new WebSocket(`/ws/host/${gameId}`);

// First message: authenticate
ws.send({ type: 'auth', token: Auth.getToken() });

// Receive auth response
{ type: 'auth_ok' }

// Receive initial game state
{ type: 'game_state', state: { discovered_links, node_positions, tags } }

// Send visual state (same as before, but lighter)
{
  type: 'visual_state',
  viewport: { x, y, k, width, height },
  selected_node: 'nodeId',
  frontier_highlight: true,
  exploration_mode: true,
  nodes: { [nodeId]: { x, y, highlighted, dimmed, ... } },
  links: { [linkKey]: { highlighted, dimmed, ... } }
}

// Send positions update (debounced)
{ type: 'positions_update', positions: { [nodeId]: { x, y } } }

// Send tag update
{ type: 'tag_update', zone: 'zoneName', tags: ['warning', 'later'] }

// Send manual discovery (clicked placeholder)
{ type: 'manual_discovery', source: 'src', target: 'dst' }
```

**Host Receives:**
```javascript
// Discovery from mod (or manual from another client)
{ type: 'discovery', propagated: [{ source, target }, ...] }

// Tag update from mod
{ type: 'tag_update', zone: 'zoneName', tags: [...] }

// Heartbeat
{ type: 'ping' }  // Respond with { type: 'pong' }
```

**Viewer Connection:**
```javascript
// Connect (no auth)
ws = new WebSocket(`/ws/viewer/${gameId}`);

// Receive current visual state (or waiting message)
{ type: 'visual_state', ... }
// or
{ type: 'waiting', message: 'Waiting for host to connect' }

// Receive updates
{ type: 'visual_state', ... }
{ type: 'positions_update', ... }
{ type: 'discovery', propagated: [...] }
{ type: 'tag_update', ... }

// Heartbeat
{ type: 'ping' }  // Respond with { type: 'pong' }
```

### 7.2 Host State Flow

When mod discovers:
1. Server broadcasts `{ type: 'discovery', propagated: [...] }`
2. Host receives, applies discoveries to local state
3. Host re-renders graph
4. Host sends `visual_state` to viewers (after 50ms delay)

When host manually discovers:
1. Host sends `{ type: 'manual_discovery', source, target }`
2. Server propagates, broadcasts `{ type: 'discovery', propagated: [...] }`
3. Host receives own broadcast, applies discoveries
4. Host re-renders and syncs visual state

### 7.3 Backward Compatibility

The 4-letter session codes are removed. Old URLs like `?viewer=true&session=ABCD`
should redirect to `/` with an error message.

## 8. Exploration Changes (exploration.js)

### 8.1 Discovery Flow

```javascript
async function discoverArea(areaId, fromNodeId, viaLink) {
  if (State.getBackendMode() === 'online') {
    // Server-side propagation
    // Note: actual discovery happens when we receive the 'discovery' event
    // from WebSocket (even for our own discoveries)
    Sync.sendManualDiscovery(fromNodeId, areaId);
  } else {
    // Offline mode: existing client-side propagation
    discoverWithPreexisting(areaId, fromNodeId, viaLink);
    State.saveExplorationToStorage();
  }
}
```

### 8.2 Applying Server Discoveries

```javascript
function applyPropagatedDiscoveries(propagated) {
  for (const { source, target } of propagated) {
    // Mark nodes as discovered
    State.discoverNode(source);
    State.discoverNode(target);

    // Mark link as discovered
    State.discoverLink(source, target, isBidirectional(source, target));
  }

  // Trigger re-render
  State.emit('graphNeedsRender');
}
```

### 8.3 Undiscovery

In online mode, undiscovery is not supported initially. The server is the source of
truth, and we don't have an "undiscover" API endpoint.

Options:
1. Disable undiscover button in online mode
2. Add `DELETE /api/games/{gameId}/discoveries` endpoint later

For MVP: **disable undiscover in online mode**.

## 9. UI Changes (ui.js)

### 9.1 Landing Page

```html
<section id="landing-page">
  <h1>Elden Ring Fog Gate Visualizer</h1>
  <p>Track your randomizer progress</p>

  <div class="login-section">
    <button id="login-twitch">Login with Twitch</button>
    <p>Or use <a href="/?offline=true">offline mode</a></p>
  </div>
</section>
```

### 9.2 Dashboard Page

```html
<section id="dashboard-page" hidden>
  <header>
    <h1>Your Games</h1>
    <span id="user-display-name"></span>
    <button id="logout-btn">Logout</button>
  </header>

  <div id="games-list">
    <!-- Populated dynamically -->
  </div>

  <div id="new-game-section">
    <h2>Start New Game</h2>
    <input type="file" id="spoiler-log-upload" accept=".txt" />
    <input type="text" id="game-label" placeholder="Game label (optional)" />
    <button id="create-game-btn">Create Game</button>
  </div>
</section>
```

### 9.3 Game Card Component

```html
<div class="game-card" data-game-id="xxx">
  <div class="game-info">
    <span class="game-label">My Playthrough</span>
    <span class="game-seed">Seed: 123456789</span>
    <span class="game-progress">45/180 (25%)</span>
  </div>
  <div class="game-actions">
    <a href="/play/xxx" class="btn-play">Play</a>
    <button class="btn-delete">Delete</button>
  </div>
</div>
```

### 9.4 Play Page Changes

- Remove file upload (game already exists)
- Add "Back to Dashboard" link
- Show game label in header
- Disable "Reset Exploration" (server is source of truth)
- Disable undiscover (no API for it yet)

### 9.5 Stream Modal Changes

Replace session code with direct URL:

```
Viewer URL: https://example.com/watch/username/game-id
```

With counter options:
```
https://example.com/watch/username/game-id?counter=br&size=md
```

## 10. Pages Implementation

### 10.1 Landing Page (pages/landing.js)

```javascript
export function initLanding() {
  document.getElementById('login-twitch').onclick = () => Auth.login();

  // Check for token in URL (OAuth callback)
  const params = new URLSearchParams(location.search);
  const token = params.get('token');
  if (token) {
    Auth.handleCallback(token);
  }
}
```

### 10.2 Dashboard Page (pages/dashboard.js)

```javascript
export async function initDashboard() {
  // Load user info
  const user = await Auth.getUser();
  document.getElementById('user-display-name').textContent = user.displayName;

  // Load games
  const { games } = await Api.getMyGames();
  renderGamesList(games);

  // Setup new game form
  document.getElementById('create-game-btn').onclick = createNewGame;
}

async function createNewGame() {
  const file = document.getElementById('spoiler-log-upload').files[0];
  const label = document.getElementById('game-label').value;

  const text = await file.text();
  const { seed, graphData } = SpoilerLogParser.parse(text);

  // Convert to zone_pairs format for API
  const zonePairs = graphData.links.map(link => ({
    source: link.source,
    destination: link.target,
    type: link.type,
    source_details: link.sourceDetails,
    target_details: link.targetDetails,
  }));

  const { gameId } = await Api.createGame({
    seed,
    runId: `web_${Date.now()}`,  // Generate run_id for web uploads
    label: label || null,
    zonePairs,
  });

  Router.navigate(`/play/${gameId}`);
}
```

### 10.3 User Games Page (pages/viewer-list.js)

```javascript
export async function initUserGames(username) {
  const user = await Api.getUser(username);
  const { games } = await Api.getUserGames(username);

  document.getElementById('viewer-username').textContent = user.displayName;
  renderPublicGamesList(games, username);
}
```

## 11. Implementation Order

### Phase 1: Foundation
1. `router.js` - Basic routing
2. `auth.js` - Token storage, login redirect
3. `api.js` - REST client
4. Update `index.html` - Add page sections

### Phase 2: Pages
5. Landing page
6. Dashboard page
7. Public user games page

### Phase 3: Play Mode Integration
8. Update `state.js` - Add backendMode, gameId
9. Update `sync.js` - New WebSocket protocol for host
10. Update `exploration.js` - Server-side discovery
11. Update `ui.js` - Disable unavailable features

### Phase 4: Viewer Mode
12. Update `sync.js` - New WebSocket protocol for viewer
13. Viewer counter compatibility

### Phase 5: Polish
14. Error handling
15. Loading states
16. Toast notifications
17. Offline mode verification

## 12. Migration Notes

### 12.1 Breaking Changes

- Old session URLs (`?viewer=true&session=XXXX`) no longer work
- localStorage exploration data not migrated to server

### 12.2 Deprecation

- `server.py` (legacy simple server) - Keep for reference but mark deprecated
- 4-letter session codes - Removed entirely

### 12.3 Offline Mode

Accessible via `/?offline=true`. Works exactly as current implementation:
- File upload
- localStorage persistence
- Client-side propagation
- **No WebSocket sync** (streaming removed from offline mode)

Offline mode = purely local, single user. The 4-letter session code system is
removed entirely.

### 12.4 Mod is Optional

The mod automates discovery tracking but is not required. Without the mod:
1. User uploads spoiler log via dashboard → creates a game
2. User plays Elden Ring
3. When traversing a fog gate, user clicks the corresponding placeholder on the website
4. Server propagates, viewers see the update in real-time

This is the same workflow as the current system, but with server persistence
instead of localStorage. The mod simply adds automation (fog detection →
automatic server update → no alt-tab needed).
