//! Core traits - abstractions for platform-specific implementations
//!
//! These traits define the interface for reading game state. The actual
//! implementations live in the `platform` module and use Windows APIs.
//! For testing, mock implementations can be provided.

use super::types::{PlayerPosition, SpEffectDebugInfo, WarpInfo};

// =============================================================================
// GAME STATE READER
// =============================================================================

/// Read player state from the game
///
/// This trait abstracts the memory reading operations needed to track
/// the player's position and animation state.
pub trait GameStateReader {
    /// Block until the game is fully loaded (menu timer > 0)
    fn wait_for_game_loaded(&self);

    /// Read current player position and map data
    ///
    /// Returns None if position data is not available (e.g., during loading)
    fn read_position(&self) -> Option<PlayerPosition>;

    /// Read current animation ID
    fn read_animation(&self) -> Option<u32>;
}

// =============================================================================
// WARP DETECTOR
// =============================================================================

/// Detect warp requests from GameMan
///
/// GameMan contains global game state including warp requests and destinations.
pub trait WarpDetector {
    /// Check if a warp is currently requested
    fn is_warp_requested(&self) -> bool;

    /// Get the destination entity ID for the current warp (spawn point)
    ///
    /// This returns the spawn point entity ID, which is the fog gate randomizer
    /// entity ID (755890xxx) for fog gate traversals.
    fn get_destination_entity_id(&self) -> u32;

    /// Get the target grace entity ID (fast travel destination)
    ///
    /// This value is captured via a function hook on lua_warp when the player
    /// initiates fast travel from the map menu. The hook intercepts the grace
    /// entity ID passed as a parameter to the warp function.
    ///
    /// Note: Reading from GameMan offset 0xB3C does not work in practice.
    fn get_target_grace_entity_id(&self) -> u32;

    /// Get the destination map ID for the current warp
    fn get_destination_map_id(&self) -> u32;

    /// Get full warp information
    fn get_warp_info(&self) -> Option<WarpInfo>;
}

// =============================================================================
// SPEFFECT CHECKER
// =============================================================================

/// Check active SpEffects on the player
///
/// SpEffects are status effects applied to the player character.
/// Some teleportation methods can be detected via SpEffects.
pub trait SpEffectChecker {
    /// Check if player has a specific SpEffect active
    fn has_sp_effect(&self, sp_effect_id: u32) -> bool;

    /// Check if player has any of the given SpEffects active
    fn has_any_sp_effect(&self, sp_effect_ids: &[u32]) -> bool {
        sp_effect_ids.iter().any(|&id| self.has_sp_effect(id))
    }

    /// Get debug info about the SpEffect reading chain
    fn get_debug_info(&self) -> SpEffectDebugInfo;
}

// =============================================================================
// TEST MOCKS
// =============================================================================

#[cfg(test)]
pub mod mocks {
    use super::*;

    /// Mock GameStateReader for testing
    pub struct MockGameState {
        pub positions: Vec<Option<PlayerPosition>>,
        pub animations: Vec<Option<u32>>,
        pub frame: std::cell::Cell<usize>,
    }

    impl MockGameState {
        pub fn new(positions: Vec<Option<PlayerPosition>>, animations: Vec<Option<u32>>) -> Self {
            Self {
                positions,
                animations,
                frame: std::cell::Cell::new(0),
            }
        }

        pub fn advance_frame(&self) {
            self.frame.set(self.frame.get() + 1);
        }

        pub fn current_frame(&self) -> usize {
            self.frame.get()
        }
    }

    impl GameStateReader for MockGameState {
        fn wait_for_game_loaded(&self) {
            // No-op in tests
        }

        fn read_position(&self) -> Option<PlayerPosition> {
            self.positions.get(self.frame.get()).cloned().flatten()
        }

        fn read_animation(&self) -> Option<u32> {
            self.animations.get(self.frame.get()).cloned().flatten()
        }
    }

    /// Mock WarpDetector for testing
    pub struct MockWarpDetector {
        pub warp_requested: std::cell::Cell<bool>,
        pub dest_entity_id: std::cell::Cell<u32>,
        pub target_grace_entity_id: std::cell::Cell<u32>,
        pub dest_map_id: std::cell::Cell<u32>,
    }

    impl MockWarpDetector {
        pub fn new() -> Self {
            Self {
                warp_requested: std::cell::Cell::new(false),
                dest_entity_id: std::cell::Cell::new(0),
                target_grace_entity_id: std::cell::Cell::new(0),
                dest_map_id: std::cell::Cell::new(0),
            }
        }

        pub fn set_warp(&self, requested: bool, entity_id: u32, map_id: u32) {
            self.warp_requested.set(requested);
            self.dest_entity_id.set(entity_id);
            self.dest_map_id.set(map_id);
        }

        /// Set the target grace entity ID (simulates hook capture during fast travel)
        pub fn set_target_grace(&self, grace_entity_id: u32) {
            self.target_grace_entity_id.set(grace_entity_id);
        }
    }

    impl Default for MockWarpDetector {
        fn default() -> Self {
            Self::new()
        }
    }

    impl WarpDetector for MockWarpDetector {
        fn is_warp_requested(&self) -> bool {
            self.warp_requested.get()
        }

        fn get_destination_entity_id(&self) -> u32 {
            self.dest_entity_id.get()
        }

        fn get_target_grace_entity_id(&self) -> u32 {
            self.target_grace_entity_id.get()
        }

        fn get_destination_map_id(&self) -> u32 {
            self.dest_map_id.get()
        }

        fn get_warp_info(&self) -> Option<WarpInfo> {
            Some(WarpInfo {
                warp_requested: self.warp_requested.get(),
                destination_entity_id: self.dest_entity_id.get(),
                destination_map_id: self.dest_map_id.get(),
            })
        }
    }

    /// Mock SpEffectChecker for testing
    pub struct MockSpEffectChecker {
        pub active_effects: std::cell::RefCell<Vec<u32>>,
    }

    impl MockSpEffectChecker {
        pub fn new() -> Self {
            Self {
                active_effects: std::cell::RefCell::new(Vec::new()),
            }
        }

        pub fn set_effects(&self, effects: Vec<u32>) {
            *self.active_effects.borrow_mut() = effects;
        }
    }

    impl Default for MockSpEffectChecker {
        fn default() -> Self {
            Self::new()
        }
    }

    impl SpEffectChecker for MockSpEffectChecker {
        fn has_sp_effect(&self, sp_effect_id: u32) -> bool {
            self.active_effects.borrow().contains(&sp_effect_id)
        }

        fn get_debug_info(&self) -> SpEffectDebugInfo {
            let effects = self.active_effects.borrow().clone();
            SpEffectDebugInfo {
                active_effects: effects.clone(),
                has_teleport_effect: effects.contains(&4280),
                ..Default::default()
            }
        }
    }
}
