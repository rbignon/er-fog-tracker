// Game state reading from Elden Ring memory
//
// Encapsulates all memory pointer chains and provides a clean interface
// to read player position, animation state, and other game data.

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

// =============================================================================
// CONSTANTS
// =============================================================================

/// Offset of PlayRegionId within CS::FieldArea structure
const FIELD_AREA_PLAY_REGION_ID_OFFSET: usize = 0xE4;

/// Animation ID for fog wall traversal
pub const FOG_WALL_ANIM_ID: u32 = 60060;

/// Invalid map_id value (during loading screens)
const INVALID_MAP_ID: u32 = 0xFFFFFFFF;

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

    /// Check if player is currently in fog wall traversal animation
    pub fn is_in_fog_animation(&self) -> bool {
        self.read_animation()
            .map(|a| a == FOG_WALL_ANIM_ID)
            .unwrap_or(false)
    }
}
