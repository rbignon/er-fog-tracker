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
type WarpFn = unsafe extern "system" fn(u64, u64, u32);

/// Our detour function that intercepts warp calls
unsafe extern "system" fn warp_hook(arg1: u64, arg2: u64, grace_id_param: u32) {
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
        error!("Warp detour not found when calling original function");
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
