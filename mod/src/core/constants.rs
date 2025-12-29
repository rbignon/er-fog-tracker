//! Game constants - entity ranges, timeouts, memory offsets
//!
//! All magic numbers from Elden Ring that we need for fog gate tracking.
//! Animation IDs are in the `animations` module.

use num_enum::TryFromPrimitive;
use std::time::Duration;

// =============================================================================
// FOG GATE RANDOMIZER ENTITY RANGES
// =============================================================================

/// Minimum entity ID used by Fog Gate Randomizer
pub const FOG_RANDO_ENTITY_MIN: u32 = 755890000;

/// Maximum entity ID used by Fog Gate Randomizer
pub const FOG_RANDO_ENTITY_MAX: u32 = 755899999;

// =============================================================================
// TIMEOUTS
// =============================================================================

/// Maximum time a pending warp can stay unresolved before being discarded
pub const WARP_TIMEOUT: Duration = Duration::from_secs(30);

// =============================================================================
// MEMORY OFFSETS (documented here, used in platform/)
// =============================================================================

/// Offset of PlayRegionId within CS::FieldArea structure
pub const FIELD_AREA_PLAY_REGION_ID_OFFSET: usize = 0xE4;

/// Invalid map_id value (during loading screens)
pub const INVALID_MAP_ID: u32 = 0xFFFFFFFF;

/// Offset from PlayerIns to SpEffectCtrl
pub const SPEFFECT_CTRL_OFFSET: usize = 0x178;

/// SpEffect ID for teleportation (debug display only)
pub const DEBUG_TELEPORT_SPEFFECT_ID: u32 = 4280;

/// Offset of warp_requested bool in GameMan structure
pub const GAMEMAN_WARP_REQUESTED_OFFSET: usize = 0x10;

/// Offset of initial_area_entity_id in GameMan structure (spawn point)
pub const GAMEMAN_INITIAL_AREA_ENTITY_ID_OFFSET: usize = 0x3C;

/// Offset of load_target_block_id in GameMan structure
pub const GAMEMAN_LOAD_TARGET_BLOCK_ID_OFFSET: usize = 0xAC8;

/// SpEffect ID applied after spawning at a grace
pub const GRACE_SPAWN_SPEFFECT_ID: u32 = 106;

/// Offset of death_count in GameDataMan structure
pub const GAMEDATAMAN_DEATH_COUNT_OFFSET: usize = 0x94;

// =============================================================================
// INVENTORY READING
// =============================================================================

/// Item category for Goods (consumables, key items)
pub const ITEM_CATEGORY_GOODS: u8 = 4;

/// Offset from PlayerGameData to key_items_head pointer
pub const KEY_ITEMS_HEAD_OFFSET: usize = 0x428;

/// Offset from PlayerGameData to key_items_count
pub const KEY_ITEMS_COUNT_OFFSET: usize = 0x430;

/// Size of each inventory entry (EquipInventoryDataListEntry)
pub const INVENTORY_ENTRY_SIZE: usize = 0x18;

/// Offset to item_id within inventory entry
pub const INVENTORY_ENTRY_ITEM_ID_OFFSET: usize = 0x04;

/// Offset to quantity within inventory entry
pub const INVENTORY_ENTRY_QUANTITY_OFFSET: usize = 0x08;

// =============================================================================
// GREAT RUNES
// =============================================================================

/// Great Rune param_ids (restored versions)
///
/// Unrestored versions use param_ids 8148-8153, which map to Godrick-Malenia.
#[repr(u32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, TryFromPrimitive)]
pub enum GreatRune {
    Godrick = 191,
    Radahn = 192,
    Morgott = 193,
    Rykard = 194,
    Mohg = 195,
    Malenia = 196,
    Unborn = 10080,
}

/// Range of unrestored Great Rune param_ids (8148-8153 → Godrick-Malenia)
pub const GREAT_RUNE_UNRESTORED_RANGE: std::ops::RangeInclusive<u32> = 8148..=8153;

impl GreatRune {
    /// Try to match a param_id, normalizing unrestored to restored
    pub fn from_param_id(param_id: u32) -> Option<Self> {
        // Normalize unrestored (8148-8153) to restored (191-196)
        let normalized = if GREAT_RUNE_UNRESTORED_RANGE.contains(&param_id) {
            param_id - *GREAT_RUNE_UNRESTORED_RANGE.start() + Self::Godrick as u32
        } else {
            param_id
        };

        Self::try_from(normalized).ok()
    }

    /// Get the raw param_id
    pub fn as_u32(self) -> u32 {
        self as u32
    }
}

/// Messmer's Kindling param_id (discovered via debug dump)
pub const MESSMERS_KINDLING: u32 = 2008021;

/// Extra slots to scan beyond key_items_count
/// The count field can be inaccurate, so we scan a buffer beyond it
pub const INVENTORY_SCAN_BUFFER: u32 = 20;
