//! Game constants - animation IDs, entity ranges, timeouts
//!
//! All magic numbers from Elden Ring that we need for fog gate tracking.

use std::time::Duration;

// =============================================================================
// TELEPORT ANIMATION IDS
// =============================================================================

/// Fog wall traversal animation
pub const ANIM_FOG_WALL: u32 = 60060;

/// "Back to entrance" animation (used by some fog gates)
pub const ANIM_BACK_TO_ENTRANCE: u32 = 60460;

/// Waygate teleport animation
pub const ANIM_WAYGATE: u32 = 60490;

/// Sending gate (blue variant) animation
pub const ANIM_SENDING_GATE_BLUE: u32 = 60470;

/// Sending gate (red variant) animation
pub const ANIM_SENDING_GATE_RED: u32 = 60472;

/// Pureblood Knight's Medal item use animation
pub const ANIM_MEDAL: u32 = 50340;

/// Horned Remains teleport animation
pub const ANIM_HORNED_REMAINS: u32 = 60010;

/// Liurnia Divine Tower door teleport animation
pub const ANIM_LIURNIA_TOWER_DOOR: u32 = 12202126;

/// Post-boss warp animation (after defeating a boss)
pub const ANIM_POST_BOSS_WARP: u32 = 12020210;

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
