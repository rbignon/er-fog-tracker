//! Game constants - animation IDs, entity ranges, timeouts
//!
//! All magic numbers from Elden Ring that we need for fog gate tracking.

use num_enum::TryFromPrimitive;
use std::time::Duration;

// =============================================================================
// TELEPORT ANIMATION IDS
// =============================================================================

/// Known animation IDs in Elden Ring
#[repr(u32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, TryFromPrimitive)]
pub enum Animation {
    // -------------------------------------------------------------------------
    // Teleport animations
    // -------------------------------------------------------------------------
    /// Fog wall traversal animation
    FogWall = 60060,
    /// "Back to entrance" animation (used by some fog gates)
    BackToEntrance = 60460,
    /// Waygate teleport animation
    Waygate = 60490,
    /// Sending gate (blue variant) animation
    SendingGateBlue = 60470,
    /// Sending gate (red variant) animation
    SendingGateRed = 60472,
    /// Pureblood Knight's Medal item use animation
    Medal = 50340,
    /// Horned Remains teleport animation
    HornedRemains = 60010,
    /// Liurnia Divine Tower door teleport animation
    LiurniaTowerDoor = 12202126,
    /// Post-boss warp animation (after defeating a boss)
    PostBossWarp = 12020210,
    /// Erdtree burn cutscene warp (Melina sacrifices herself)
    ErdtreeBurn = 68110,
    /// Placidusax lie down animation (access to boss arena)
    PlacidusaxLieDown = 67010,

    // -------------------------------------------------------------------------
    // Other known animations
    // -------------------------------------------------------------------------
    /// Memory of Grace item use animation
    ItemUseMemory = 50230,
    /// Spawn animation
    Spawn = 63000,
}

impl Animation {
    /// Try to convert a raw animation ID to an Animation
    ///
    /// Note: Returns None for unknown animations and for 0 (idle/no animation).
    pub fn from_anim_id(anim_id: u32) -> Option<Self> {
        Self::try_from(anim_id).ok()
    }

    /// Get the raw animation ID
    pub fn as_u32(self) -> u32 {
        self as u32
    }

    /// Check if this animation is a teleport animation
    pub fn is_teleport(self) -> bool {
        matches!(
            self,
            Self::FogWall
                | Self::BackToEntrance
                | Self::Waygate
                | Self::SendingGateBlue
                | Self::SendingGateRed
                | Self::Medal
                | Self::HornedRemains
                | Self::LiurniaTowerDoor
                | Self::PostBossWarp
                | Self::ErdtreeBurn
                | Self::PlacidusaxLieDown
        )
    }

    /// Get a short label for teleport animations (for logging)
    ///
    /// Returns None for non-teleport animations.
    pub fn teleport_label(self) -> Option<&'static str> {
        match self {
            Self::FogWall => Some("FOG"),
            Self::BackToEntrance => Some("BACK_TO_ENTRANCE"),
            Self::Waygate => Some("WAYGATE"),
            Self::SendingGateBlue | Self::SendingGateRed => Some("SENDING_GATE"),
            Self::Medal => Some("MEDAL"),
            Self::HornedRemains => Some("HORNED_REMAINS"),
            Self::LiurniaTowerDoor => Some("LIURNIA_TOWER_DOOR"),
            Self::PostBossWarp => Some("POST_BOSS_WARP"),
            Self::ErdtreeBurn => Some("ERDTREE_BURN"),
            Self::PlacidusaxLieDown => Some("PLACIDUSAX_LIE_DOWN"),
            _ => None,
        }
    }

    /// Get the full animation name (for debug display)
    pub fn name(self) -> &'static str {
        match self {
            Self::FogWall => "FOG_WALL",
            Self::BackToEntrance => "BACK_TO_ENTRANCE",
            Self::Waygate => "WAYGATE",
            Self::SendingGateBlue => "SENDING_GATE_BLUE",
            Self::SendingGateRed => "SENDING_GATE_RED",
            Self::Medal => "ITEM_USE_MEDAL",
            Self::HornedRemains => "HORNED_REMAINS",
            Self::LiurniaTowerDoor => "LIURNIA_TOWER_DOOR",
            Self::PostBossWarp => "POST_BOSS_WARP",
            Self::ErdtreeBurn => "ERDTREE_BURN",
            Self::PlacidusaxLieDown => "PLACIDUSAX_LIE_DOWN",
            Self::ItemUseMemory => "ITEM_USE_MEMORY",
            Self::Spawn => "SPAWN",
        }
    }
}

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

/// Offset of initial_area_entity_id in GameMan structure
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
