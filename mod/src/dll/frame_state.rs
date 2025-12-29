//! Frame snapshot - captures all game state readings at the start of each frame
//!
//! This module provides a FrameSnapshot struct that captures all game state
//! in a single pass at the beginning of each frame. This eliminates redundant
//! memory reads throughout the frame processing.
//!
//! The snapshot implements GameStateReader and WarpDetector traits, allowing
//! it to be used seamlessly with TrackerSession.

use crate::core::traits::{GameStateReader, WarpDetector};
use crate::core::types::{PlayerPosition, WarpInfo};
use crate::eldenring::{GameMan, GameState};

/// A snapshot of all game state captured at the start of a frame.
///
/// This struct caches all values that would otherwise be read multiple times
/// during frame processing. By capturing everything upfront, we reduce
/// memory reads from ~70/frame to ~5-15/frame.
#[derive(Debug, Clone)]
pub struct FrameSnapshot {
    /// Player position (None if loading screen)
    position: Option<PlayerPosition>,
    /// Current animation ID
    animation: Option<u32>,
    /// Whether a warp is currently requested
    warp_requested: bool,
    /// Destination entity ID for the current warp (spawn point, for fog gates)
    destination_entity_id: u32,
    /// Target grace entity ID (fast travel destination, captured via warp hook)
    target_grace_entity_id: u32,
    /// Destination map ID for the current warp
    destination_map_id: u32,
}

impl FrameSnapshot {
    /// Capture a snapshot of the current game state.
    ///
    /// This performs all necessary memory reads in a single pass:
    /// - Player position (from GameState)
    /// - Current animation (from GameState)
    /// - Warp requested flag (from GameMan)
    /// - Destination entity ID (from GameMan)
    /// - Destination map ID (from GameMan)
    /// - Target grace entity ID (from warp hook)
    pub fn capture(game_state: &GameState, game_man: &GameMan) -> Self {
        // Read all values once
        let position = game_state.read_position();
        let animation = game_state.read_animation();
        let warp_requested = game_man.is_warp_requested();
        let destination_entity_id = game_man.get_destination_entity_id();
        let destination_map_id = game_man.get_destination_map_id();

        // Target grace entity ID comes from the warp hook, which intercepts
        // the lua_warp function call when the player initiates fast travel.
        // Note: Reading from GameMan offset 0xB3C does not work.
        let target_grace_entity_id = crate::eldenring::warp_hook::get_captured_grace_entity_id();

        Self {
            position,
            animation,
            warp_requested,
            destination_entity_id,
            target_grace_entity_id,
            destination_map_id,
        }
    }
}

impl GameStateReader for FrameSnapshot {
    fn wait_for_game_loaded(&self) {
        // No-op for snapshot - the game is already loaded when we capture
    }

    fn read_position(&self) -> Option<PlayerPosition> {
        self.position.clone()
    }

    fn read_animation(&self) -> Option<u32> {
        self.animation
    }
}

impl WarpDetector for FrameSnapshot {
    fn is_warp_requested(&self) -> bool {
        self.warp_requested
    }

    fn get_destination_entity_id(&self) -> u32 {
        self.destination_entity_id
    }

    fn get_target_grace_entity_id(&self) -> u32 {
        self.target_grace_entity_id
    }

    fn get_destination_map_id(&self) -> u32 {
        self.destination_map_id
    }

    fn get_warp_info(&self) -> Option<WarpInfo> {
        Some(WarpInfo {
            warp_requested: self.warp_requested,
            destination_entity_id: self.destination_entity_id,
            destination_map_id: self.destination_map_id,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Note: Full integration tests require Windows APIs.
    // Unit tests here verify the trait implementations work correctly
    // with pre-populated snapshots.

    fn make_snapshot(
        position: Option<PlayerPosition>,
        animation: Option<u32>,
        warp_requested: bool,
        dest_entity_id: u32,
        dest_map_id: u32,
    ) -> FrameSnapshot {
        FrameSnapshot {
            position,
            animation,
            warp_requested,
            destination_entity_id: dest_entity_id,
            target_grace_entity_id: 0,
            destination_map_id: dest_map_id,
        }
    }

    #[test]
    fn test_game_state_reader_position() {
        let pos = PlayerPosition::new(0x3C2C2400, 100.0, 50.0, 200.0, Some(12345));
        let snapshot = make_snapshot(Some(pos.clone()), Some(123), false, 0, 0);

        let read_pos = snapshot.read_position().unwrap();
        assert_eq!(read_pos.map_id, pos.map_id);
        assert_eq!(read_pos.x, pos.x);
        assert_eq!(read_pos.y, pos.y);
        assert_eq!(read_pos.z, pos.z);
    }

    #[test]
    fn test_game_state_reader_position_none() {
        let snapshot = make_snapshot(None, Some(123), false, 0, 0);
        assert!(snapshot.read_position().is_none());
    }

    #[test]
    fn test_game_state_reader_animation() {
        let snapshot = make_snapshot(None, Some(60002), false, 0, 0);
        assert_eq!(snapshot.read_animation(), Some(60002));
    }

    #[test]
    fn test_warp_detector_not_requested() {
        let snapshot = make_snapshot(None, None, false, 0, 0);
        assert!(!snapshot.is_warp_requested());
        assert_eq!(snapshot.get_destination_entity_id(), 0);
        assert_eq!(snapshot.get_destination_map_id(), 0);
    }

    #[test]
    fn test_warp_detector_requested() {
        let snapshot = make_snapshot(None, None, true, 755890042, 0x0A0A1000);
        assert!(snapshot.is_warp_requested());
        assert_eq!(snapshot.get_destination_entity_id(), 755890042);
        assert_eq!(snapshot.get_destination_map_id(), 0x0A0A1000);
    }

    #[test]
    fn test_warp_info() {
        let snapshot = make_snapshot(None, None, true, 755890042, 0x0A0A1000);
        let info = snapshot.get_warp_info().unwrap();
        assert!(info.warp_requested);
        assert_eq!(info.destination_entity_id, 755890042);
        assert_eq!(info.destination_map_id, 0x0A0A1000);
    }
}
