# TODO

## Before v1.0

### Security

- [x] **XSS vulnerability in error display** - `web/js/ui.js:37,41` uses `innerHTML` for error messages. Replace with `textContent` or sanitize HTML with DOMPurify.
- [x] **Spoiler log size limit** - `server/fogtracker/api/spoiler.py:36-44` accepts unlimited input. Add `max_length=1_000_000` to `SpoilerParseRequest.spoiler_log`.
- [x] **Tag array size validation** - `server/fogtracker/websocket/mod.py:367-392` and `host.py:61-83` accept arbitrary tag arrays. Add size limit (e.g., 50 items max).

### Stability

- [ ] **Unsafe unwrap in launcher** - `mod/src/launcher/app.rs:375` uses `clone().unwrap()` after `has_token()` check. Replace with `if let Some(token) = ...` pattern.
- [ ] **WebSocket send error handling** - Multiple files in `web/js/sync/` call `ws.send()` without try-catch. Wrap all `send()` calls.
- [ ] **WebSocket reconnection race condition** - `web/js/sync/common.js:127-193` resets `gameWsIsReconnecting` flag before calling `handleGameWsDisconnect()`, allowing duplicate reconnection attempts.

### Documentation

- [ ] **Create CHANGELOG.md** - Document v1.0 features and known limitations.
- [ ] **Exclude docs/specs/ from release** - Internal design documents (IMPLEMENTATION_PLAN, REFACTORING_PLAN, etc.) should not be in the public release.

---

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

- [ ] **Regenerate zone_matching fixtures** - 3 skipped tests in `server/tests/unit/test_zone_matching.py` need fixture regeneration with `source_id`/`target_id`.
- [ ] **Add database layer tests** - No tests for game persistence, user management, or transactions.
- [ ] **Add WebSocket integration tests** - No end-to-end tests for mod ↔ server communication.
- [ ] **Add concurrent discovery tests** - No tests for race conditions with multiple simultaneous discoveries.

---

## Nice to Have

### Features

- [ ] **Offline discovery queue** - Queue discoveries locally when server is unreachable, replay on reconnect.
- [ ] **Mod connection indicator** - Show on website whether the in-game mod is currently connected.

### Code Quality

- [ ] **Browser compatibility** - Optional chaining (`?.`) not supported in Safari < 13.1. Consider transpilation or document minimum browser requirements more prominently.
- [ ] **Modal initialization memory leak** - `web/js/sync/host.js:271-352` can add duplicate event listeners on retry. Add initialization guard.
- [ ] **Position bounds checking** - `web/js/state.js:504-507` accepts any finite number. Add reasonable bounds (e.g., `±1e6`).
- [ ] **Launcher error messages** - `mod/src/launcher/app.rs:1192-1203` GUI init `expect()` calls could show more informative message boxes.

### Documentation

- [ ] **SECURITY.md** - Add security guidelines and vulnerability reporting process.
- [ ] **TROUBLESHOOTING.md** - Document common issues and solutions.
- [ ] **FAQ.md** - Frequently asked questions.

---

## Known Limitations

These are documented and accepted:

- Auto-detection is not 100% reliable (some edge cases will always exist)
