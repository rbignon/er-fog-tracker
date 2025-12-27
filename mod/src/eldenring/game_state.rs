//! Elden Ring GameStateReader implementation
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

use crate::core::constants::{FIELD_AREA_PLAY_REGION_ID_OFFSET, INVALID_MAP_ID};
use crate::core::map_utils::format_map_id;
use crate::core::traits::GameStateReader;
use crate::core::types::PlayerPosition;

/// Elden Ring game state reader
///
/// Uses libeldenring to read from Elden Ring's memory.
pub struct GameState {
    pointers: Pointers,
    play_region_id_ptr: PointerChain<u32>,
}

impl GameState {
    /// Create a new GameState reader
    pub fn new() -> Self {
        let pointers = Pointers::new();

        // Create pointer chain for PlayRegionId (FieldArea + 0xE4)
        let play_region_id_ptr = PointerChain::<u32>::new(&[
            pointers.base_addresses.field_area,
            FIELD_AREA_PLAY_REGION_ID_OFFSET,
        ]);

        Self {
            pointers,
            play_region_id_ptr,
        }
    }

    /// Get base addresses (for creating SpEffect and GameMan readers)
    pub fn base_addresses(&self) -> &libeldenring::prelude::base_addresses::BaseAddresses {
        &self.pointers.base_addresses
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}

impl GameStateReader for GameState {
    fn wait_for_game_loaded(&self) {
        let poll_interval = Duration::from_millis(100);
        loop {
            if let Some(menu_timer) = self.pointers.menu_timer.read() {
                if menu_timer > 0. {
                    break;
                }
            }
            std::thread::sleep(poll_interval);
        }
    }

    fn read_position(&self) -> Option<PlayerPosition> {
        let [x, y, z, _, _] = self.pointers.global_position.read()?;
        let map_id = self.pointers.global_position.read_map_id()?;

        // Check if position is valid (not during loading screen)
        if map_id == INVALID_MAP_ID || (x == 0.0 && y == 0.0 && z == 0.0) {
            return None;
        }

        Some(PlayerPosition {
            map_id,
            map_id_str: format_map_id(map_id),
            x,
            y,
            z,
            play_region_id: self.play_region_id_ptr.read(),
        })
    }

    fn read_animation(&self) -> Option<u32> {
        self.pointers.cur_anim.read()
    }
}
