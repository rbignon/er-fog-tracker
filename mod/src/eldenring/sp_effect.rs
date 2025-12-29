//! Elden Ring SpEffectChecker implementation
//!
//! Reads active SpEffects from the player character in Elden Ring.

use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Threading::GetCurrentProcess;

use super::memory::MemoryReader;
use crate::core::constants::{DEBUG_TELEPORT_SPEFFECT_ID, SPEFFECT_CTRL_OFFSET};
use crate::core::traits::SpEffectChecker;
use crate::core::types::SpEffectDebugInfo;

/// Elden Ring SpEffect checker
///
/// SpEffects are stored in a linked list structure on the player.
/// Structure (from CE Table analysis):
/// - WorldChrMan[player_ins] -> PlayerIns
/// - PlayerIns[0x178] -> SpEffectCtrl
/// - SpEffectCtrl[0x8] -> First node pointer
/// - Each node: +0x8 = SpEffect ID (u32), +0x30 = Next node pointer
pub struct SpEffect {
    proc: HANDLE,
    world_chr_man: usize,
    player_ins_offset: usize,
}

impl MemoryReader for SpEffect {
    fn proc(&self) -> HANDLE {
        self.proc
    }
}

impl SpEffect {
    /// Create a new SpEffect reader
    pub fn new(base_addresses: &libeldenring::prelude::base_addresses::BaseAddresses) -> Self {
        let version = get_version();

        // PlayerIns offset varies by game version
        let player_ins_offset: usize = match version {
            Version::V1_02_0
            | Version::V1_02_1
            | Version::V1_02_2
            | Version::V1_02_3
            | Version::V1_03_0
            | Version::V1_03_1
            | Version::V1_03_2
            | Version::V1_04_0
            | Version::V1_04_1
            | Version::V1_05_0
            | Version::V1_06_0 => 0x18468,
            _ => 0x1E508, // V1_07_0 and later (including 2.x)
        };

        Self {
            proc: unsafe { GetCurrentProcess() },
            world_chr_man: base_addresses.world_chr_man,
            player_ins_offset,
        }
    }

    /// Get PlayerIns pointer
    fn get_player_ins(&self) -> Option<usize> {
        // WorldChrMan -> [player_ins_offset] -> PlayerIns
        let world_chr_man_ptr = self.read_ptr(self.world_chr_man)?;
        self.read_ptr(world_chr_man_ptr + self.player_ins_offset)
    }

    /// Quick check for teleport effect (avoids full debug info scan)
    ///
    /// This is a lightweight alternative to get_debug_info() when you only
    /// need to know if the teleport effect is active. Uses has_sp_effect()
    /// which does an early return on match.
    pub fn has_teleport_effect(&self) -> bool {
        self.has_sp_effect(DEBUG_TELEPORT_SPEFFECT_ID)
    }
}

impl SpEffectChecker for SpEffect {
    fn has_sp_effect(&self, target_id: u32) -> bool {
        let player_ins = match self.get_player_ins() {
            Some(ptr) if ptr != 0 => ptr,
            _ => return false,
        };

        // Get SpEffectCtrl: PlayerIns + 0x178
        let sp_effect_ctrl = match self.read_ptr(player_ins + SPEFFECT_CTRL_OFFSET) {
            Some(ptr) if ptr != 0 => ptr,
            _ => return false,
        };

        // Get first node: SpEffectCtrl + 0x8
        let mut node = match self.read_ptr(sp_effect_ctrl + 0x8) {
            Some(ptr) => ptr,
            None => return false,
        };

        // Iterate through linked list (max 256 iterations to prevent infinite loops)
        let mut count = 0;
        while node != 0 && count < 256 {
            // Read SpEffect ID at node + 0x8
            if let Some(sp_id) = self.read_u32(node + 0x8) {
                if sp_id == target_id {
                    return true;
                }
            }
            // Move to next node at +0x30
            node = self.read_ptr(node + 0x30).unwrap_or(0);
            count += 1;
        }

        false
    }

    fn get_debug_info(&self) -> SpEffectDebugInfo {
        let world_chr_man_ptr = self.read_ptr(self.world_chr_man);

        let player_ins =
            world_chr_man_ptr.and_then(|wcm| self.read_ptr(wcm + self.player_ins_offset));

        let sp_effect_ctrl = player_ins.and_then(|pi| self.read_ptr(pi + SPEFFECT_CTRL_OFFSET));

        let first_node = sp_effect_ctrl.and_then(|ctrl| self.read_ptr(ctrl + 0x8));

        // Count active SpEffects and collect first few IDs
        let mut active_effects: Vec<u32> = Vec::new();
        let mut node = first_node.unwrap_or(0);
        let mut count = 0;
        while node != 0 && count < 32 {
            if let Some(sp_id) = self.read_u32(node + 0x8) {
                if sp_id != 0 {
                    active_effects.push(sp_id);
                }
            }
            node = self.read_ptr(node + 0x30).unwrap_or(0);
            count += 1;
        }

        let has_teleport_effect = active_effects.contains(&DEBUG_TELEPORT_SPEFFECT_ID);

        SpEffectDebugInfo {
            world_chr_man_base: self.world_chr_man,
            world_chr_man_ptr,
            player_ins_offset: self.player_ins_offset,
            player_ins,
            sp_effect_ctrl,
            first_node,
            active_effects,
            has_teleport_effect,
        }
    }
}
