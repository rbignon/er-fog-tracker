# TODO

## After v1.0

### Security Hardening

- [ ] **WebSocket message rate limiting** - `server/fogtracker/websocket/mod.py:673-962` has no per-connection rate limit. Add limit (e.g., 10 discoveries/second).
- [ ] **Discovery propagation race condition** - `server/fogtracker/game_logic.py:264-305` lacks row-level locking when called from REST API (`api/games.py:272-303`).
- [ ] **OAuth state cleanup race** - `server/fogtracker/api/auth.py:25-48` cleanup can delete valid states during concurrent requests. Consider database-backed state store.
- [ ] **Path traversal hardening** - `server/fogtracker/websocket/mod.py:68-106` log upload should validate paths stay within `reports_dir`.

### Configuration Enforcement

- [ ] **Enforce max_viewers_per_game** - `server/fogtracker/config.py:41` defines `max_viewers_per_game=10` but it's never checked.

### Error Handling

- [ ] **localStorage quota handling** - `web/js/state.js:547,600` silently fails on quota exceeded. Show toast notification to user.
- [ ] **Grace mapping load failure** - `server/fogtracker/zone_resolver.py:448-456` silently falls back to empty mapping. Make failure more visible.

### Tests

- [ ] **Add database layer tests** - No tests for game persistence, user management, or transactions.
- [ ] **Add WebSocket integration tests** - No end-to-end tests for mod ↔ server communication.
- [ ] **Add concurrent discovery tests** - No tests for race conditions with multiple simultaneous discoveries.

---

## Nice to Have

### Features

- [ ] **Mod information to server** - Send from mod information about Great Runes/Kindlings/deaths to server to display them on the website
- [ ] **Display issues related to tags or search results** the popup is still visible, but the graph consider no selected nodes
- [ ] **Auto discover update** on website, after an auto-discover, the text is in black on the overlay mode, and the host must center on the target node, and be careful to not open the popup over the node
- [ ] **Offline discovery queue** - Queue discoveries locally when server is unreachable, replay on reconnect.

### Code Quality

- [ ] **Modal initialization memory leak** - `web/js/sync/host.js:271-352` can add duplicate event listeners on retry. Add initialization guard.
- [ ] **Position bounds checking** - `web/js/state.js:504-507` accepts any finite number. Add reasonable bounds (e.g., `±1e6`).
- [ ] **Launcher error messages** - `mod/src/launcher/app.rs:1192-1203` GUI init `expect()` calls could show more informative message boxes.

### Documentation

- [ ] **SECURITY.md** - Add security guidelines and vulnerability reporting process.
- [ ] **TROUBLESHOOTING.md** - Document common issues and solutions.
- [ ] **FAQ.md** - Frequently asked questions.