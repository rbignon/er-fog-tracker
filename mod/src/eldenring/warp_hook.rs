//! Warp function hook for capturing grace entity ID during fast travel
//!
//! Hooks the game's lua_warp function to intercept the grace destination
//! when the player uses fast travel from the map menu.

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::OnceLock;

use retour::GenericDetour;
use tracing::{debug, error, info, warn};

/// Captured grace entity ID from the last warp call
static CAPTURED_GRACE_ENTITY_ID: AtomicU32 = AtomicU32::new(0);

/// Re-entrancy guard flag
static IN_HOOK: AtomicBool = AtomicBool::new(false);

/// The detour instance (must be kept alive)
static WARP_DETOUR: OnceLock<GenericDetour<WarpFn>> = OnceLock::new();

/// Warp function signature: (arg1, arg2, grace_entity_id - 0x3e8)
type WarpFn = unsafe extern "system" fn(u64, u64, u32);

/// RAII guard for re-entrancy protection.
/// Automatically releases the lock when dropped, ensuring it's always released
/// regardless of how the function exits (normal return, early return, or panic).
struct ReentrancyGuard;

impl ReentrancyGuard {
    /// Try to acquire the guard. Returns None if already in the hook.
    fn try_acquire() -> Option<Self> {
        if IN_HOOK.swap(true, Ordering::SeqCst) {
            None // Already in hook
        } else {
            Some(ReentrancyGuard)
        }
    }
}

impl Drop for ReentrancyGuard {
    fn drop(&mut self) {
        IN_HOOK.store(false, Ordering::SeqCst);
    }
}

/// Call the original warp function safely.
///
/// Wrapped in catch_unwind to prevent double-panic scenarios.
/// If this panics, we just continue - the warp won't execute but the game won't crash.
unsafe fn call_original_safe(arg1: u64, arg2: u64, grace_id_param: u32) {
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if let Some(detour) = WARP_DETOUR.get() {
            detour.call(arg1, arg2, grace_id_param);
        }
    }));
}

/// Our detour function that intercepts warp calls.
///
/// This is an `extern "system"` function called by the game. Panics across FFI
/// boundaries are undefined behavior, so we wrap the entire body in `catch_unwind`.
///
/// # Safety
/// - AssertUnwindSafe is correct here because we don't modify shared state before
///   potential panic points, and unwinding will safely drop all local values.
unsafe extern "system" fn warp_hook(arg1: u64, arg2: u64, grace_id_param: u32) {
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        // Re-entrancy guard: if we're already in the hook, just call original
        let _guard = match ReentrancyGuard::try_acquire() {
            Some(guard) => guard,
            None => {
                warn!("Warp hook re-entrancy detected, skipping capture");
                // Protected call to avoid panic in re-entrant path blocking future warps
                call_original_safe(arg1, arg2, grace_id_param);
                return;
            }
        };

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
        } else {
            // This should never happen (hook shouldn't be called if detour not installed),
            // but if it does, try to call original anyway to avoid breaking fast travel
            error!("Warp detour not found - attempting fallback call");
            call_original_safe(arg1, arg2, grace_id_param);
        }

        // Guard automatically released here via Drop
    }));

    // Handle panic: log error, ensure original function is called, reset guard
    if let Err(panic_info) = result {
        // Format panic message - this could technically panic but it's very unlikely
        let panic_msg = if let Some(s) = panic_info.downcast_ref::<&str>() {
            format!("Warp hook panicked: {}", s)
        } else if let Some(s) = panic_info.downcast_ref::<String>() {
            format!("Warp hook panicked: {}", s)
        } else {
            "Warp hook panicked with unknown error".to_string()
        };

        // Log the error (ignore if this fails)
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            error!("{}", panic_msg);
        }));

        // CRITICAL: Call original function to avoid breaking game state
        // Protected to avoid double-panic UB
        call_original_safe(arg1, arg2, grace_id_param);

        // Clear re-entrancy flag in case panic happened before guard drop
        IN_HOOK.store(false, Ordering::SeqCst);
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
        .map_err(|_| "Warp hook already installed".to_string())?;

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
