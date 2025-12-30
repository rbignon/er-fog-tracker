//! Elden Ring WarpDetector implementation
//!
//! Reads warp state from Elden Ring's GameMan structure.

use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Threading::GetCurrentProcess;

use super::memory::MemoryReader;
use crate::core::constants::{
    GAMEMAN_INITIAL_AREA_ENTITY_ID_OFFSET, GAMEMAN_LOAD_TARGET_BLOCK_ID_OFFSET,
    GAMEMAN_WARP_REQUESTED_OFFSET,
};
use crate::core::traits::WarpDetector;
use crate::core::types::WarpInfo;

/// Elden Ring warp detection via GameMan structure
///
/// Reads from Elden Ring's GameMan structure to detect warp requests
/// and destination information.
pub struct GameMan {
    proc: HANDLE,
    game_man: usize,
}

impl MemoryReader for GameMan {
    fn proc(&self) -> HANDLE {
        self.proc
    }
}

impl GameMan {
    /// Create a new GameMan reader
    pub fn new(base_addresses: &libeldenring::prelude::base_addresses::BaseAddresses) -> Self {
        Self {
            proc: unsafe { GetCurrentProcess() },
            game_man: base_addresses.game_man,
        }
    }

    /// Get the GameMan pointer
    fn get_game_man_ptr(&self) -> Option<usize> {
        self.read_ptr(self.game_man)
    }
}

impl WarpDetector for GameMan {
    fn is_warp_requested(&self) -> bool {
        self.get_game_man_ptr()
            .and_then(|gm| self.read_bool(gm + GAMEMAN_WARP_REQUESTED_OFFSET))
            .unwrap_or(false)
    }

    fn get_destination_entity_id(&self) -> u32 {
        self.get_game_man_ptr()
            .and_then(|gm| self.read_u32(gm + GAMEMAN_INITIAL_AREA_ENTITY_ID_OFFSET))
            .unwrap_or(0)
    }

    fn get_target_grace_entity_id(&self) -> u32 {
        // Note: Reading from GameMan offset 0xB3C does not work - it returns 0.
        // The actual value is captured via the warp_hook module which intercepts
        // the lua_warp function call. FrameSnapshot reads from the hook instead.
        0
    }

    fn get_destination_map_id(&self) -> u32 {
        self.get_game_man_ptr()
            .and_then(|gm| self.read_u32(gm + GAMEMAN_LOAD_TARGET_BLOCK_ID_OFFSET))
            .unwrap_or(0)
    }

    fn get_warp_info(&self) -> Option<WarpInfo> {
        let gm = self.get_game_man_ptr()?;
        Some(WarpInfo {
            warp_requested: self
                .read_bool(gm + GAMEMAN_WARP_REQUESTED_OFFSET)
                .unwrap_or(false),
            destination_entity_id: self
                .read_u32(gm + GAMEMAN_INITIAL_AREA_ENTITY_ID_OFFSET)
                .unwrap_or(0),
            destination_map_id: self
                .read_u32(gm + GAMEMAN_LOAD_TARGET_BLOCK_ID_OFFSET)
                .unwrap_or(0),
        })
    }
}
