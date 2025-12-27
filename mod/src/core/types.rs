//! Core types - platform-independent data structures
//!
//! These types represent game state and are used throughout the tracker.

use super::map_utils::format_map_id;

// =============================================================================
// PLAYER POSITION
// =============================================================================

/// Current player position snapshot
#[derive(Clone, Debug, PartialEq)]
pub struct PlayerPosition {
    pub map_id: u32,
    pub map_id_str: String,
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub play_region_id: Option<u32>,
}

impl PlayerPosition {
    /// Create a new PlayerPosition
    pub fn new(map_id: u32, x: f32, y: f32, z: f32, play_region_id: Option<u32>) -> Self {
        Self {
            map_id,
            map_id_str: format_map_id(map_id),
            x,
            y,
            z,
            play_region_id,
        }
    }

    /// Returns position as a tuple (x, y, z)
    pub fn pos(&self) -> (f32, f32, f32) {
        (self.x, self.y, self.z)
    }
}

// =============================================================================
// WARP INFO
// =============================================================================

/// Warp information from GameMan
#[derive(Debug, Clone, PartialEq)]
pub struct WarpInfo {
    /// Whether a warp is currently requested
    pub warp_requested: bool,
    /// Entity ID of the destination (e.g., grace entity ID for fast travel)
    pub destination_entity_id: u32,
    /// Map ID (BlockId) of the destination
    pub destination_map_id: u32,
}

// =============================================================================
// SPEFFECT DEBUG INFO
// =============================================================================

/// Debug information about SpEffect reading
#[derive(Debug, Clone, Default)]
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

// =============================================================================
// TELEPORT TYPE
// =============================================================================

/// Types of teleportation events
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TeleportType {
    /// Fog wall traversal
    FogWall,
    /// Waygate or Sending gate
    Waygate,
    /// Pureblood Knight's Medal
    Medal,
    /// Coffin transport
    Coffin,
    /// Fast travel to a grace
    FastTravel,
}

impl TeleportType {
    /// Animation ID that triggers this event type
    pub fn animation_id(&self) -> Option<u32> {
        use super::constants::Animation;
        match self {
            Self::FogWall => Some(Animation::FogWall.as_u32()),
            Self::Waygate => Some(Animation::Waygate.as_u32()),
            Self::Medal => Some(Animation::Medal.as_u32()),
            Self::Coffin => None,
            Self::FastTravel => None,
        }
    }

    /// SpEffect IDs used for detection
    pub fn speffect_ids(&self) -> &'static [u32] {
        match self {
            Self::FogWall => &[],
            Self::Waygate => &[],
            Self::Medal => &[],
            Self::Coffin => &[4190, 4010, 4510],
            Self::FastTravel => &[],
        }
    }

    /// Log prefix for this event type
    pub fn name(&self) -> &'static str {
        match self {
            Self::FogWall => "FOG",
            Self::Waygate => "WAYGATE",
            Self::Medal => "MEDAL",
            Self::Coffin => "COFFIN",
            Self::FastTravel => "FAST_TRAVEL",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_player_position_new() {
        let pos = PlayerPosition::new(0x3C2C2400, 100.0, 50.0, 200.0, Some(12345));
        assert_eq!(pos.map_id, 0x3C2C2400);
        assert_eq!(pos.map_id_str, "m60_44_36_00");
        assert_eq!(pos.x, 100.0);
        assert_eq!(pos.y, 50.0);
        assert_eq!(pos.z, 200.0);
        assert_eq!(pos.play_region_id, Some(12345));
    }

    #[test]
    fn test_player_position_pos_tuple() {
        let pos = PlayerPosition::new(0, 1.0, 2.0, 3.0, None);
        assert_eq!(pos.pos(), (1.0, 2.0, 3.0));
    }

    #[test]
    fn test_teleport_type_names() {
        assert_eq!(TeleportType::FogWall.name(), "FOG");
        assert_eq!(TeleportType::Waygate.name(), "WAYGATE");
        assert_eq!(TeleportType::Coffin.name(), "COFFIN");
    }
}
