# Warp Function Hook Implementation Plan

## Problem Statement

The mod needs to detect the **grace entity ID** when the player initiates a fast travel from the map menu. The current approach reads `GameMan + 0xB3C` (target_grace_entity_id), but this offset returns 0 in practice.

After investigation:
- The offsets `0xB30` and `0xB3C` in `GameMan` point to `F32Vector3` (coordinates), not entity IDs
- No other tool (practice-tool, EldenRingTool) reads the grace destination from memory
- The practice-tool uses a hardcoded grace database and calls the warp function directly

## Proposed Solution

Hook the game's warp function to intercept the grace entity ID when the game calls it for fast travel.

### How it works

The practice-tool reveals that the warp function has this signature:

```rust
type WarpFn = extern "system" fn(arg1: u64, arg2: u64, grace_id_minus_1000: u32);
```

When the game performs a fast travel:
1. The UI sets up the warp parameters
2. The game calls `lua_warp` with `(arg1, arg2, grace_entity_id - 0x3e8)`
3. The warp executes

By hooking this function, we can capture `grace_entity_id = arg3 + 0x3e8` before the warp happens.

### Why this works

- `libeldenring` already provides `base_addresses.lua_warp` for all supported game versions
- The function address is resolved via AOB pattern scanning at compile time
- No additional pattern maintenance required (libeldenring handles it)

## Implementation Steps

### Step 1: Add retour dependency

In `mod/Cargo.toml`:

```toml
[target.'cfg(windows)'.dependencies]
retour = { version = "0.3", default-features = false }
```

Note: Avoid the `static-detour` feature as it requires nightly Rust. Use the generic detour instead.

### Step 2: Create warp_hook module

Create `mod/src/eldenring/warp_hook.rs`:

```rust
//! Warp function hook for capturing grace entity ID during fast travel
//!
//! Hooks the game's lua_warp function to intercept the grace destination
//! when the player uses fast travel from the map menu.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::OnceLock;

use retour::GenericDetour;
use tracing::{debug, error, info};

/// Captured grace entity ID from the last warp call
static CAPTURED_GRACE_ENTITY_ID: AtomicU32 = AtomicU32::new(0);

/// The detour instance (must be kept alive)
static WARP_DETOUR: OnceLock<GenericDetour<WarpFn>> = OnceLock::new();

/// Warp function signature: (arg1, arg2, grace_entity_id - 0x3e8)
type WarpFn = extern "system" fn(u64, u64, u32);

/// Our detour function that intercepts warp calls
extern "system" fn warp_hook(arg1: u64, arg2: u64, grace_id_param: u32) {
    // The game passes grace_entity_id - 0x3e8 (1000)
    let grace_entity_id = grace_id_param.wrapping_add(0x3e8);

    // Store for later retrieval
    CAPTURED_GRACE_ENTITY_ID.store(grace_entity_id, Ordering::SeqCst);

    debug!(
        "Warp hook triggered: param={}, grace_entity_id={}",
        grace_id_param, grace_entity_id
    );

    // Call the original function
    if let Some(detour) = WARP_DETOUR.get() {
        detour.call(arg1, arg2, grace_id_param);
    }
}

/// Install the warp function hook
///
/// # Safety
/// This function modifies the game's code at runtime. Must only be called once.
pub unsafe fn install(lua_warp_addr: usize) -> Result<(), String> {
    // func_warp = lua_warp + 2 (skip the RET instruction from previous function)
    let func_warp_addr = lua_warp_addr + 2;

    info!(
        "Installing warp hook at lua_warp=0x{:X}, func_warp=0x{:X}",
        lua_warp_addr, func_warp_addr
    );

    let target: WarpFn = std::mem::transmute(func_warp_addr);

    let detour = GenericDetour::<WarpFn>::new(target, warp_hook)
        .map_err(|e| format!("Failed to create detour: {}", e))?;

    detour
        .enable()
        .map_err(|e| format!("Failed to enable detour: {}", e))?;

    // Store the detour to keep it alive
    WARP_DETOUR
        .set(detour)
        .map_err(|_| "Warp hook already installed")?;

    info!("Warp hook installed successfully");
    Ok(())
}

/// Get the grace entity ID captured from the last warp call
///
/// Returns 0 if no warp has been captured yet.
pub fn get_captured_grace_entity_id() -> u32 {
    CAPTURED_GRACE_ENTITY_ID.load(Ordering::SeqCst)
}

/// Clear the captured grace entity ID
///
/// Call this after processing a warp to avoid stale data.
pub fn clear_captured_grace_entity_id() {
    CAPTURED_GRACE_ENTITY_ID.store(0, Ordering::SeqCst);
}

/// Check if the hook is installed
pub fn is_installed() -> bool {
    WARP_DETOUR.get().is_some()
}
```

### Step 3: Update eldenring module

In `mod/src/eldenring/mod.rs`, add:

```rust
pub mod warp_hook;
```

### Step 4: Install hook during initialization

In `mod/src/dll/tracker.rs`, in `FogRandoTracker::new()`:

```rust
// After creating GameState
let base_addresses = game_state.base_addresses();

// Install warp hook
unsafe {
    if let Err(e) = crate::eldenring::warp_hook::install(base_addresses.lua_warp) {
        error!("Failed to install warp hook: {}", e);
        // Continue without the hook - fall back to existing behavior
    }
}
```

### Step 5: Use captured grace ID in session

In `mod/src/core/session.rs`, modify the warp detection logic:

```rust
// When warp_requested becomes true, check for captured grace ID
if warp_requested && !self.was_warp_requested {
    // Try to get grace ID from hook first
    #[cfg(target_os = "windows")]
    let captured_grace = crate::eldenring::warp_hook::get_captured_grace_entity_id();

    #[cfg(not(target_os = "windows"))]
    let captured_grace = 0u32;

    if captured_grace != 0 {
        self.captured_target_grace = Some(captured_grace);
        // Clear for next warp
        #[cfg(target_os = "windows")]
        crate::eldenring::warp_hook::clear_captured_grace_entity_id();
    } else {
        // Fall back to memory read (may not work)
        let target = warp_detector.get_target_grace_entity_id();
        self.captured_target_grace = if target != 0 { Some(target) } else { None };
    }
}
```

### Step 6: Update WarpDetector trait (optional)

Add method to `core/traits.rs`:

```rust
pub trait WarpDetector {
    // ... existing methods ...

    /// Get grace entity ID from hook (if available)
    fn get_hooked_grace_entity_id(&self) -> Option<u32> {
        None  // Default implementation for tests
    }
}
```

## File Changes Summary

| File | Change |
|------|--------|
| `mod/Cargo.toml` | Add `retour` dependency |
| `mod/src/eldenring/mod.rs` | Add `pub mod warp_hook;` |
| `mod/src/eldenring/warp_hook.rs` | **New file** - Hook implementation |
| `mod/src/dll/tracker.rs` | Install hook during init |
| `mod/src/core/session.rs` | Use captured grace ID |

## Testing Strategy

### Manual Testing

1. Start the game with the mod
2. Check logs for "Warp hook installed successfully"
3. Fast travel to a grace from the map
4. Check logs for "Warp hook triggered: grace_entity_id=XXXXX"
5. Verify the entity ID matches the expected grace

### Test Cases

| Action | Expected Result |
|--------|-----------------|
| Fast travel to The First Step | `grace_entity_id = 1042362951` |
| Fast travel to Church of Elleh | `grace_entity_id = 1042362950` |
| Fast travel to Roundtable Hold | `grace_entity_id = 11102950` |
| Traverse a fog gate | Hook NOT triggered (different path) |
| Use waygate | Hook NOT triggered (different path) |

## Risks and Mitigations

### Risk 1: Anti-cheat detection (EAC)

**Risk**: Easy Anti-Cheat might detect the function hook.

**Mitigation**:
- The mod already uses `hudhook` which hooks DirectX
- libeldenring is used by the practice-tool without issues
- The hook is read-only (doesn't modify game behavior)

### Risk 2: Game version incompatibility

**Risk**: New game versions might break the hook.

**Mitigation**:
- `libeldenring` maintains AOB patterns for all versions
- The mod already depends on `libeldenring` for version detection
- If the hook fails, fall back to existing behavior

### Risk 3: Thread safety

**Risk**: The warp function might be called from any thread.

**Mitigation**:
- Use `AtomicU32` for thread-safe storage
- The detour library handles thread suspension during install

### Risk 4: Retour stability

**Risk**: The `retour` library might have bugs.

**Mitigation**:
- `retour` is a maintained fork of `detour-rs`
- Widely used in game modding community
- Can fall back to `minhook-rs` if needed

## Alternative Approaches Considered

### 1. Read from CSLuaEventManager

**Rejected**: The structure doesn't expose grace selection directly. The practice-tool uses it for function arguments, not for reading selection state.

### 2. Read from GameMan offsets

**Rejected**: Offsets `0xB30`/`0xB3C` point to `F32Vector3`, not entity IDs. Returns 0 in practice.

### 3. Position-based matching after warp

**Current approach**: Works but less precise for areas with multiple graces (e.g., Stormveil has 9 graces in the same map).

### 4. Parse BonfireWarpParam

**Not explored**: Would require loading game params. More complex than hooking.

## Timeline

| Phase | Tasks |
|-------|-------|
| Phase 1 | Add dependency, create warp_hook module |
| Phase 2 | Integrate with tracker initialization |
| Phase 3 | Update session to use captured ID |
| Phase 4 | Test with various grace destinations |
| Phase 5 | Handle edge cases and fallbacks |

## Success Criteria

1. Hook installs without crash
2. Grace entity ID is captured for all fast travel warps
3. No regression for fog gate / waygate detection
4. Works across supported game versions
5. No anti-cheat detection issues
