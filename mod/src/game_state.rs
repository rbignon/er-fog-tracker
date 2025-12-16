// Game state reading from Elden Ring memory
//
// Encapsulates all memory pointer chains and provides a clean interface
// to read player position, animation state, and other game data.

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows::Win32::System::Threading::GetCurrentProcess;

// =============================================================================
// INTERNAL CONSTANTS
// =============================================================================

/// Offset of PlayRegionId within CS::FieldArea structure
const FIELD_AREA_PLAY_REGION_ID_OFFSET: usize = 0xE4;

/// Invalid map_id value (during loading screens)
const INVALID_MAP_ID: u32 = 0xFFFFFFFF;

/// Offset from PlayerIns to SpEffectCtrl
const SPEFFECT_CTRL_OFFSET: usize = 0x178;

/// SpEffect ID for teleportation (not actually used - kept for debug display)
const DEBUG_TELEPORT_SPEFFECT_ID: u32 = 4280;

// =============================================================================
// TELEPORT TYPE ENUM
// =============================================================================

/// Types of teleportation events tracked by the mod
///
/// Each variant represents a different way the player can be teleported
/// in the Fog Gate Randomizer. The enum encapsulates the detection logic
/// (animation IDs and SpEffect IDs) for each type.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TeleportType {
    /// Fog wall traversal - walking through a fog gate
    FogWall,
    /// Waygate or Sending gate - hand turns blue before teleport
    Waygate,
    /// Pureblood Knight's Medal - item use teleport
    Medal,
    /// Coffin transport - no animation, detected via SpEffect only
    Coffin,
}

impl TeleportType {
    /// Animation ID that triggers this event type
    ///
    /// Returns None for event types detected via SpEffect only (e.g., Coffin)
    pub fn animation_id(&self) -> Option<u32> {
        match self {
            Self::FogWall => Some(60060),
            Self::Waygate => Some(60490),
            Self::Medal => Some(50340),
            Self::Coffin => None,
        }
    }

    /// SpEffect IDs that must be active for detection
    ///
    /// Returns empty slice for event types detected via animation only.
    /// For Medal: requires one of the SpEffects in addition to animation.
    /// For Coffin: requires one of the SpEffects (no animation check).
    pub fn speffect_ids(&self) -> &'static [u32] {
        match self {
            Self::FogWall => &[],
            Self::Waygate => &[],
            Self::Medal => &[502160, 502161],
            Self::Coffin => &[4190, 4010, 4510],
        }
    }

    /// Whether this event requires SpEffect check for detection
    pub fn requires_speffect(&self) -> bool {
        match self {
            Self::FogWall | Self::Waygate => false,
            Self::Medal | Self::Coffin => true,
        }
    }

    /// Log prefix for this event type
    pub fn name(&self) -> &'static str {
        match self {
            Self::FogWall => "FOG",
            Self::Waygate => "WAYGATE",
            Self::Medal => "MEDAL",
            Self::Coffin => "COFFIN",
        }
    }
}

// =============================================================================
// MAP ID UTILITIES
// =============================================================================

/// Format a map_id as a string "mWW_XX_YY_DD"
pub fn format_map_id(map_id: u32) -> String {
    let ww = (map_id >> 24) & 0xFF;
    let xx = (map_id >> 16) & 0xFF;
    let yy = (map_id >> 8) & 0xFF;
    let dd = map_id & 0xFF;
    format!("m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd)
}

// =============================================================================
// PLAYER POSITION
// =============================================================================

/// Current player position snapshot
#[derive(Clone, Debug)]
pub struct PlayerPosition {
    pub map_id: u32,
    pub map_id_str: String,
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub play_region_id: Option<u32>,
}

impl PlayerPosition {
    /// Returns position as a tuple (x, y, z)
    pub fn pos(&self) -> (f32, f32, f32) {
        (self.x, self.y, self.z)
    }
}

// =============================================================================
// GAME STATE READER
// =============================================================================

/// Reads game state from Elden Ring memory
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

    /// Block until the game is fully loaded (menu timer > 0)
    pub fn wait_for_game_loaded(&self) {
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

    /// Read current player position and map data
    ///
    /// Returns None if position data is not available (e.g., during loading)
    pub fn read_position(&self) -> Option<PlayerPosition> {
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

    /// Read current animation ID
    pub fn read_animation(&self) -> Option<u32> {
        self.pointers.cur_anim.read()
    }

    /// Check if player is currently in the animation for a given teleport type
    ///
    /// Returns false for teleport types that don't have an animation (e.g., Coffin)
    pub fn is_in_animation(&self, event_type: TeleportType) -> bool {
        match event_type.animation_id() {
            Some(expected_anim) => self
                .read_animation()
                .map(|a| a == expected_anim)
                .unwrap_or(false),
            None => false,
        }
    }

    /// Get base addresses (for creating SpEffectReader)
    pub fn base_addresses(&self) -> &libeldenring::prelude::base_addresses::BaseAddresses {
        &self.pointers.base_addresses
    }
}

// =============================================================================
// SPEFFECT READER
// =============================================================================

/// Reads active SpEffects from the player character
///
/// SpEffects are stored in a linked list structure on the player.
/// Structure (from CE Table analysis):
/// - WorldChrMan[player_ins] -> PlayerIns
/// - PlayerIns[0x178] -> SpEffectCtrl
/// - SpEffectCtrl[0x8] -> First node pointer
/// - Each node: +0x8 = SpEffect ID (u32), +0x30 = Next node pointer
pub struct SpEffectReader {
    proc: HANDLE,
    world_chr_man: usize,
    player_ins_offset: usize,
}

impl SpEffectReader {
    /// Create a new SpEffectReader
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

    /// Read a u32 from the given address
    fn read_u32(&self, addr: usize) -> Option<u32> {
        if addr == 0 {
            return None;
        }
        let mut value: u32 = 0;
        unsafe {
            ReadProcessMemory(
                self.proc,
                addr as _,
                &mut value as *mut _ as _,
                std::mem::size_of::<u32>(),
                None,
            )
            .ok()
            .map(|_| value)
        }
    }

    /// Read a pointer (u64) from the given address
    fn read_ptr(&self, addr: usize) -> Option<usize> {
        if addr == 0 {
            return None;
        }
        let mut value: u64 = 0;
        unsafe {
            ReadProcessMemory(
                self.proc,
                addr as _,
                &mut value as *mut _ as _,
                std::mem::size_of::<u64>(),
                None,
            )
            .ok()
            .map(|_| value as usize)
        }
    }

    /// Get PlayerIns pointer
    fn get_player_ins(&self) -> Option<usize> {
        // WorldChrMan -> [player_ins_offset] -> PlayerIns
        let world_chr_man_ptr = self.read_ptr(self.world_chr_man)?;
        self.read_ptr(world_chr_man_ptr + self.player_ins_offset)
    }

    /// Check if player has a specific SpEffect active
    pub fn has_sp_effect(&self, target_id: u32) -> bool {
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

    /// Check if player has any of the SpEffects for a given teleport type
    ///
    /// Returns true if any of the event's SpEffect IDs are active.
    /// Returns false for event types that don't require SpEffect checks.
    pub fn has_event_effect(&self, event_type: TeleportType) -> bool {
        let ids = event_type.speffect_ids();
        if ids.is_empty() {
            return false;
        }
        ids.iter().any(|&id| self.has_sp_effect(id))
    }

    /// Get debug info about the SpEffect reading chain
    /// Returns a struct with diagnostic information
    pub fn get_debug_info(&self) -> SpEffectDebugInfo {
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

/// Debug information about SpEffect reading
#[derive(Debug, Clone)]
pub struct SpEffectDebugInfo {
    pub world_chr_man_base: usize,
    pub world_chr_man_ptr: Option<usize>,
    pub player_ins_offset: usize,
    pub player_ins: Option<usize>,
    pub sp_effect_ctrl: Option<usize>,
    pub first_node: Option<usize>,
    pub active_effects: Vec<u32>,
    pub has_teleport_effect: bool,
}
