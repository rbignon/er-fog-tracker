//! Warp tracking state machine
//!
//! This module contains the core logic for detecting fog gate traversals.
//! It is platform-independent and can be tested without Windows APIs.

use std::time::Instant;

use super::animations::get_teleport_type;
use super::constants::WARP_TIMEOUT;
use super::entity_utils::is_fog_rando_entity;
use super::traits::{GameStateReader, WarpDetector};
use super::types::PlayerPosition;

// =============================================================================
// PENDING WARP
// =============================================================================

/// Pending warp event (entry position recorded, waiting for exit)
#[derive(Clone, Debug)]
pub struct PendingWarp {
    /// Entry position when the warp started
    pub entry: PlayerPosition,
    /// Entity ID of the warp destination (captured when warp_requested becomes true)
    pub destination_entity_id: u32,
    /// Transport type inferred from animation
    pub transport_type: String,
    /// When this pending warp was created (for timeout detection)
    pub created_at: Instant,
    /// Whether warp_requested was true at any point during this warp
    pub warp_was_requested: bool,
}

impl PendingWarp {
    /// Check if this pending warp has timed out
    pub fn is_timed_out(&self) -> bool {
        self.created_at.elapsed() > WARP_TIMEOUT
    }
}

// =============================================================================
// DISCOVERY EVENT
// =============================================================================

/// A completed warp discovery ready to be sent to the server
#[derive(Clone, Debug, PartialEq)]
pub struct DiscoveryEvent {
    /// Entry position
    pub entry: PlayerPosition,
    /// Exit position
    pub exit: PlayerPosition,
    /// Transport type (FogWall, Waygate, etc.)
    pub transport_type: String,
    /// Destination entity ID (755890xxx for fog rando)
    pub destination_entity_id: u32,
    /// Whether warp_requested was true at any point during this warp
    pub warp_was_requested: bool,
}

impl DiscoveryEvent {
    /// Check if this discovery event is valid (not a false positive).
    ///
    /// A discovery is valid if `warp_requested` was true at some point during
    /// the warp. This filters out false positives like cutscene animations
    /// (PostBossWarp, LiurniaTowerDoor) that can play without an actual warp.
    ///
    /// Previously, we only required this for specific animation types, but
    /// empirical data shows that ALL valid warps have `warp_requested=true`,
    /// so we can apply this universally and remove the animation whitelist.
    pub fn is_valid(&self) -> bool {
        self.warp_was_requested
    }
}

// =============================================================================
// WARP TRACKER
// =============================================================================

/// Core warp tracking state machine
///
/// This struct contains the platform-independent logic for detecting
/// fog gate traversals. It uses the GameStateReader and WarpDetector
/// traits to read game state.
///
/// # Detection Strategy
///
/// Two triggers can start tracking a warp:
/// 1. **Animation trigger**: Detect teleport animation start → record entry position
/// 2. **Entity trigger**: warp_requested becomes true with fog rando entity ID
///    (755890xxx) → record entry position even without known animation
///
/// Then:
/// - When warp_requested becomes true → capture dest_entity_id
/// - When animation ends + position readable → emit discovery event
pub struct WarpTracker {
    /// Pending fog rando warp (entry recorded, waiting for exit)
    pending_warp: Option<PendingWarp>,
    /// Whether we were in a teleport animation last frame
    was_in_teleport_anim: bool,
    /// Whether position was readable last frame (to detect loading screens)
    was_position_readable: bool,
    /// Whether warp_requested was true last frame (to detect transition)
    was_warp_requested: bool,
}

impl WarpTracker {
    /// Create a new WarpTracker
    pub fn new() -> Self {
        Self {
            pending_warp: None,
            was_in_teleport_anim: false,
            was_position_readable: false,
            was_warp_requested: false,
        }
    }

    /// Check for fog gate traversals
    ///
    /// Call this every frame. Returns a DiscoveryEvent if a warp was completed.
    ///
    /// # Arguments
    ///
    /// * `game_state` - Reader for player position and animation
    /// * `warp_detector` - Reader for warp request state
    ///
    /// # Returns
    ///
    /// * `Some(DiscoveryEvent)` - A warp was completed
    /// * `None` - No warp completed this frame
    pub fn check_warp<G: GameStateReader, W: WarpDetector>(
        &mut self,
        game_state: &G,
        warp_detector: &W,
    ) -> Option<DiscoveryEvent> {
        let mut discovery = None;

        // Track loading screens
        let position = game_state.read_position();
        let position_now_readable = position.is_some();

        // Check for pending warp timeout
        if let Some(ref pending) = self.pending_warp {
            if pending.is_timed_out() {
                self.pending_warp = None;
            }
        }

        // Get current animation and warp state
        let cur_anim = game_state.read_animation();
        let is_in_teleport_anim = cur_anim.and_then(get_teleport_type).is_some();
        let transport_type = cur_anim
            .and_then(get_teleport_type)
            .unwrap_or_else(|| "UNKNOWN".to_string());

        let is_warp_requested = warp_detector.is_warp_requested();
        let dest_entity_id = warp_detector.get_destination_entity_id();

        // Entry detection - two triggers:
        //
        // 1. Animation trigger: known teleport animation just started
        if is_in_teleport_anim && !self.was_in_teleport_anim {
            if let Some(pos) = position.clone() {
                self.pending_warp = Some(PendingWarp {
                    entry: pos,
                    destination_entity_id: 0, // Will be captured when warp_requested becomes true
                    transport_type,
                    created_at: Instant::now(),
                    warp_was_requested: false,
                });
            }
        }

        // 2. Entity trigger: warp_requested just became true with fog rando entity ID
        //    This catches warps with unknown animations (e.g., animation 25032200)
        if is_warp_requested
            && !self.was_warp_requested
            && is_fog_rando_entity(dest_entity_id)
            && self.pending_warp.is_none()
        {
            if let Some(pos) = position.clone() {
                self.pending_warp = Some(PendingWarp {
                    entry: pos,
                    destination_entity_id: dest_entity_id,
                    transport_type: "FOG_RANDO".to_string(), // Unknown animation, but fog rando entity
                    created_at: Instant::now(),
                    warp_was_requested: true, // Already true since that's how we triggered
                });
            }
        }

        // Capture dest_entity_id and warp_requested state when available
        if let Some(ref mut pending) = self.pending_warp {
            // Track if warp_requested was ever true during this warp
            if is_warp_requested {
                pending.warp_was_requested = true;
            }

            // Capture dest_entity_id when it becomes available
            if pending.destination_entity_id == 0 && dest_entity_id != 0 {
                pending.destination_entity_id = dest_entity_id;
            }
        }

        // Exit detection: animation ended + position readable
        if !is_in_teleport_anim && self.was_in_teleport_anim {
            if let Some(pending) = self.pending_warp.take() {
                if let Some(exit_pos) = position.clone() {
                    discovery = Some(DiscoveryEvent {
                        entry: pending.entry,
                        exit: exit_pos,
                        transport_type: pending.transport_type,
                        destination_entity_id: pending.destination_entity_id,
                        warp_was_requested: pending.warp_was_requested,
                    });
                } else {
                    // Position not readable yet (still loading) - keep pending
                    self.pending_warp = Some(pending);
                }
            }
        }

        // Handle delayed completion: pending warp with no animation and position readable
        if discovery.is_none()
            && self.pending_warp.is_some()
            && !is_in_teleport_anim
            && position_now_readable
        {
            if let Some(pending) = self.pending_warp.take() {
                if let Some(exit_pos) = position {
                    discovery = Some(DiscoveryEvent {
                        entry: pending.entry,
                        exit: exit_pos,
                        transport_type: pending.transport_type,
                        destination_entity_id: pending.destination_entity_id,
                        warp_was_requested: pending.warp_was_requested,
                    });
                }
            }
        }

        // Update state for next frame
        self.was_in_teleport_anim = is_in_teleport_anim;
        self.was_position_readable = position_now_readable;
        self.was_warp_requested = is_warp_requested;

        // Filter out false positives (e.g., PostBossWarp without actual warp)
        discovery.filter(|d| d.is_valid())
    }

    /// Check if we just exited a loading screen (for zone query)
    ///
    /// Returns true if position went from unreadable to readable and
    /// there's no pending warp (to avoid querying when we'll get info from discovery).
    pub fn just_exited_loading_screen<G: GameStateReader>(&self, game_state: &G) -> bool {
        let position_now_readable = game_state.read_position().is_some();
        position_now_readable && !self.was_position_readable && self.pending_warp.is_none()
    }

    /// Get the current pending warp, if any
    pub fn pending_warp(&self) -> Option<&PendingWarp> {
        self.pending_warp.as_ref()
    }

    /// Check if there's a pending warp
    pub fn has_pending_warp(&self) -> bool {
        self.pending_warp.is_some()
    }

    /// Clear the pending warp (for testing or error recovery)
    pub fn clear_pending_warp(&mut self) {
        self.pending_warp = None;
    }
}

impl Default for WarpTracker {
    fn default() -> Self {
        Self::new()
    }
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    use crate::core::animations::Animation;
    use crate::core::entity_utils::is_fog_rando_entity;
    use crate::core::traits::mocks::{MockGameState, MockWarpDetector};
    use crate::core::types::PlayerPosition;

    fn make_pos(map_id: u32, x: f32, y: f32, z: f32) -> PlayerPosition {
        PlayerPosition::new(map_id, x, y, z, None)
    }

    #[test]
    fn test_basic_fog_traversal() {
        // Simulate: idle → fog animation → loading → position readable
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Frame 0: Limgrave
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Frame 1: Animation starts
                None,                                          // Frame 2: Loading
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Frame 3: Stormveil
            ],
            vec![
                Some(0),                           // Idle
                Some(Animation::FogWall.as_u32()), // Fog wall animation starts
                Some(Animation::FogWall.as_u32()), // Still in animation
                Some(0),                           // Animation ended
            ],
        );

        let warp = MockWarpDetector::new();
        // warp_requested becomes true AFTER animation starts (realistic sequence)

        let mut tracker = WarpTracker::new();

        // Frame 0: Idle, no warp yet
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        game_state.advance_frame();

        // Frame 1: Animation starts, then warp_requested becomes true
        warp.set_warp(true, 755890042, 0x0A0A1000);
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 2: Loading screen
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        game_state.advance_frame();

        // Frame 3: Animation ended + position readable → discovery!
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some());

        let d = discovery.unwrap();
        assert_eq!(d.entry.map_id, 0x3C2C2400);
        assert_eq!(d.exit.map_id, 0x0A0A1000);
        assert_eq!(d.transport_type, "FogWall");
        assert_eq!(d.destination_entity_id, 755890042);
    }

    #[test]
    fn test_no_warp_without_animation() {
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
            ],
            vec![Some(0), Some(0)], // No teleport animation
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        assert!(tracker.check_warp(&game_state, &warp).is_none());
        game_state.advance_frame();
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        assert!(!tracker.has_pending_warp());
    }

    #[test]
    fn test_pending_warp_timeout() {
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
            ],
            vec![
                Some(Animation::FogWall.as_u32()),
                Some(Animation::FogWall.as_u32()),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Start animation
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());

        // Manually set the pending warp to be timed out
        if let Some(ref mut pending) = tracker.pending_warp {
            pending.created_at = Instant::now() - Duration::from_secs(60);
        }

        game_state.advance_frame();
        tracker.check_warp(&game_state, &warp);

        // Should be cleared due to timeout
        assert!(!tracker.has_pending_warp());
    }

    #[test]
    fn test_dest_entity_captured_delayed() {
        // Fog rando sets dest_entity_id after animation starts
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)),
            ],
            vec![
                Some(Animation::FogWall.as_u32()),
                Some(Animation::FogWall.as_u32()),
                Some(0),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Animation starts, no entity ID yet
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert_eq!(tracker.pending_warp().unwrap().destination_entity_id, 0);

        // Now set the entity ID
        warp.set_warp(true, 755890123, 0x0A0A1000);

        game_state.advance_frame();
        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().destination_entity_id,
            755890123
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().destination_entity_id, 755890123);
    }

    #[test]
    fn test_is_fog_rando_entity_check() {
        assert!(is_fog_rando_entity(755890000));
        assert!(is_fog_rando_entity(755890123));
        assert!(is_fog_rando_entity(755899999));
        assert!(!is_fog_rando_entity(12345));
        assert!(!is_fog_rando_entity(0));
    }

    #[test]
    fn test_waygate_animation() {
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Limgrave
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x3C3A3800, 500.0, 0.0, 500.0)), // Liurnia
            ],
            vec![Some(0), Some(Animation::Waygate.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890999, 0x3C3A3800);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert_eq!(tracker.pending_warp().unwrap().transport_type, "Waygate");

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "Waygate");
    }

    #[test]
    fn test_sending_gate_animation() {
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)),
            ],
            vec![Some(0), Some(Animation::SendingGateBlue.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        // warp_requested becomes true AFTER animation starts (realistic sequence)
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle, no warp yet
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts, then warp_requested becomes true
        warp.set_warp(true, 755890100, 0x0A0A1000);
        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "SendingGateBlue"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "SendingGateBlue");
    }

    #[test]
    fn test_medal_animation() {
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)),
            ],
            vec![Some(0), Some(Animation::Medal.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts, warp_requested becomes true
        warp.set_warp(true, 755890200, 0x0A0A1000);
        tracker.check_warp(&game_state, &warp);
        assert_eq!(tracker.pending_warp().unwrap().transport_type, "Medal");

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "Medal");
    }

    #[test]
    fn test_back_to_entrance_animation() {
        // Animation 60460: ground teleporter after defeating dungeon boss
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Boss room
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x3C2C2400, 200.0, 0.0, 200.0)), // Dungeon entrance
            ],
            vec![Some(0), Some(Animation::BackToEntrance.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890100, 0x3C2C2400);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "BackToEntrance"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        let d = discovery.unwrap();
        assert_eq!(d.transport_type, "BackToEntrance");
        assert_eq!(d.entry.map_id, 0x0A0A1000);
        assert_eq!(d.exit.map_id, 0x3C2C2400);
    }

    #[test]
    fn test_horned_remains_animation() {
        // Animation 60010: Horned Remains item teleport (e.g., Nokron -> Farum Azula)
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C323000, 100.0, 0.0, 100.0)), // Nokron
                Some(make_pos(0x3C323000, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x3C0C1000, 500.0, 0.0, 500.0)), // Farum Azula
            ],
            vec![Some(0), Some(Animation::HornedRemains.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890200, 0x3C0C1000);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "HornedRemains"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "HornedRemains");
    }

    #[test]
    fn test_liurnia_tower_door_animation() {
        // Animation 12202126: Divine Tower of Liurnia inverted door teleport
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C3A1000, 100.0, 0.0, 100.0)), // Tower bottom
                Some(make_pos(0x3C3A1000, 100.0, 0.0, 100.0)), // Door opens
                Some(make_pos(0x3C3A1000, 100.0, 50.0, 100.0)), // Tower top (same map, different pos)
            ],
            vec![Some(0), Some(Animation::LiurniaTowerDoor.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890300, 0x3C3A1000);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "LiurniaTowerDoor"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "LiurniaTowerDoor");
    }

    #[test]
    fn test_post_boss_warp_animation() {
        // Animation 12020210: warp after defeating certain bosses (e.g., Maliketh)
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A101000, 100.0, 0.0, 100.0)), // Boss arena
                Some(make_pos(0x0A101000, 100.0, 0.0, 100.0)), // Cutscene/warp
                Some(make_pos(0x3C5A0000, 200.0, 0.0, 200.0)), // Crumbling Farum Azula
            ],
            vec![Some(0), Some(Animation::PostBossWarp.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890400, 0x3C5A0000);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "PostBossWarp"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().transport_type, "PostBossWarp");
    }

    #[test]
    fn test_erdtree_burn_animation() {
        // Animation 68110: warp when burning the Erdtree with Melina
        use crate::core::animations::Animation;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // Forge of the Giants
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // Cutscene starts
                Some(make_pos(0x0C020000, 1171.5, -820.4, 1310.6)), // Crumbling Farum Azula
            ],
            vec![Some(0), Some(Animation::ErdtreeBurn.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 12022204, 0x0C020000); // Vanilla entity ID

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "ErdtreeBurn"
        );

        game_state.advance_frame();
        let discovery = tracker.check_warp(&game_state, &warp);

        assert!(discovery.is_some());
        let d = discovery.unwrap();
        assert_eq!(d.transport_type, "ErdtreeBurn");
        assert_eq!(d.exit.map_id, 0x0C020000);
    }

    #[test]
    fn test_multiple_warps_in_succession() {
        // Complete one warp, then immediately start another
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Start at A
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Anim 1 starts
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Arrive at B
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Anim 2 starts
                Some(make_pos(0x3C3A3800, 300.0, 0.0, 300.0)), // Arrive at C
            ],
            vec![
                Some(0),
                Some(Animation::FogWall.as_u32()),
                Some(0),                           // First warp completes
                Some(Animation::FogWall.as_u32()), // Second warp starts immediately
                Some(0),                           // Second warp completes
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle at A
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        game_state.advance_frame();

        // Frame 1: Animation starts for A→B - set warp_requested now
        warp.set_warp(true, 755890001, 0x0A0A1000);
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        game_state.advance_frame();

        // Frame 2: First warp completes (A→B)
        let discovery1 = tracker.check_warp(&game_state, &warp);
        assert!(discovery1.is_some());
        assert_eq!(discovery1.unwrap().exit.map_id, 0x0A0A1000);
        game_state.advance_frame();

        // Frame 3: Second animation starts immediately
        warp.set_warp(true, 755890002, 0x3C3A3800);
        assert!(tracker.check_warp(&game_state, &warp).is_none());
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 4: Second warp completes (B→C)
        let discovery2 = tracker.check_warp(&game_state, &warp);
        assert!(discovery2.is_some());
        let d2 = discovery2.unwrap();
        assert_eq!(d2.entry.map_id, 0x0A0A1000); // Started at B
        assert_eq!(d2.exit.map_id, 0x3C3A3800); // Ended at C
    }

    #[test]
    fn test_position_null_when_animation_starts() {
        // Animation starts but position is unreadable - should not create pending warp
        let game_state = MockGameState::new(
            vec![
                None,                                          // Position unreadable
                None,                                          // Still unreadable during animation
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Now readable
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: No position
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts but no position - no pending warp
        tracker.check_warp(&game_state, &warp);
        assert!(!tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 2: Animation ends, position readable - but no entry was recorded
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_none());
    }

    #[test]
    fn test_loading_screen_delays_completion() {
        // Animation ends but position not readable yet (loading screen)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Entry
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Anim starts
                None,                                          // Animation ended, still loading
                None,                                          // Still loading
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Finally readable
            ],
            vec![
                Some(0),
                Some(Animation::FogWall.as_u32()),
                Some(0), // Animation ended
                Some(0),
                Some(0),
            ],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890042, 0x0A0A1000);

        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 2: Animation ended but loading - pending warp kept
        let d = tracker.check_warp(&game_state, &warp);
        assert!(d.is_none());
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 3: Still loading
        let d = tracker.check_warp(&game_state, &warp);
        assert!(d.is_none());
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 4: Position readable - discovery triggered
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some());
        assert_eq!(discovery.unwrap().exit.map_id, 0x0A0A1000);
    }

    #[test]
    fn test_just_exited_loading_screen() {
        let game_state = MockGameState::new(
            vec![
                None,                                          // Loading
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Loaded
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Still loaded
            ],
            vec![Some(0), Some(0), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Loading
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Just exited loading screen
        tracker.check_warp(&game_state, &warp);
        // Note: just_exited_loading_screen checks was_position_readable from previous frame
        // After check_warp, was_position_readable is now true
        // So we need to check on the transition

        // Create fresh tracker to test the method directly
        let mut tracker2 = WarpTracker::new();
        tracker2.was_position_readable = false; // Simulate previous frame was loading

        let game_state2 = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );

        assert!(tracker2.just_exited_loading_screen(&game_state2));
    }

    #[test]
    fn test_just_exited_loading_screen_with_pending_warp() {
        // Should not trigger zone query if there's a pending warp
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );

        let mut tracker = WarpTracker::new();
        tracker.was_position_readable = false;
        tracker.pending_warp = Some(PendingWarp {
            entry: make_pos(0x3C2C2400, 100.0, 0.0, 100.0),
            destination_entity_id: 755890001,
            transport_type: "FogWall".to_string(),
            created_at: Instant::now(),
            warp_was_requested: false,
        });

        // Should return false because there's a pending warp
        assert!(!tracker.just_exited_loading_screen(&game_state));
    }

    #[test]
    fn test_clear_pending_warp() {
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
            ],
            vec![
                Some(Animation::FogWall.as_u32()),
                Some(Animation::FogWall.as_u32()),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());

        tracker.clear_pending_warp();
        assert!(!tracker.has_pending_warp());
    }

    #[test]
    fn test_warp_same_map_different_position() {
        // Warp within same map (e.g., trap chest within a dungeon)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Position A
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Animation
                Some(make_pos(0x0A0A1000, 500.0, 50.0, 500.0)), // Position B (same map!)
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890050, 0x0A0A1000);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some());

        let d = discovery.unwrap();
        // Same map but different positions
        assert_eq!(d.entry.map_id, d.exit.map_id);
        assert_ne!(d.entry.pos(), d.exit.pos());
    }

    #[test]
    fn test_non_fog_rando_entity() {
        // Normal warp with non-fog-rando entity ID
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)),
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        warp.set_warp(true, 12345, 0x0A0A1000); // Non-fog-rando entity

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some());

        let d = discovery.unwrap();
        assert_eq!(d.destination_entity_id, 12345);
        assert!(!is_fog_rando_entity(d.destination_entity_id));
    }

    // =========================================================================
    // PostBossWarp false positive filtering tests
    // =========================================================================

    #[test]
    fn test_discovery_event_is_valid_with_warp_requested() {
        // All transport types require warp_was_requested=true to be valid
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, 100.0, 0.0, 100.0),
            exit: make_pos(0x0A0A1000, 105.0, 0.0, 105.0),
            transport_type: "FogWall".to_string(),
            destination_entity_id: 0,
            warp_was_requested: true,
        };
        assert!(discovery.is_valid());
    }

    #[test]
    fn test_discovery_event_is_invalid_without_warp_requested() {
        // Without warp_was_requested, all types are invalid
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, 100.0, 0.0, 100.0),
            exit: make_pos(0x0A0A1000, 105.0, 0.0, 105.0),
            transport_type: "FogWall".to_string(),
            destination_entity_id: 0,
            warp_was_requested: false,
        };
        assert!(!discovery.is_valid());
    }

    #[test]
    fn test_discovery_event_post_boss_warp_with_warp_requested() {
        // PostBossWarp with warp_requested=true is valid
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, 100.0, 0.0, 100.0),
            exit: make_pos(0x0B0B1000, 100.0, 0.0, 100.0),
            transport_type: "PostBossWarp".to_string(),
            destination_entity_id: 0,
            warp_was_requested: true,
        };
        assert!(discovery.is_valid());
    }

    #[test]
    fn test_discovery_event_post_boss_warp_false_positive() {
        // PostBossWarp without warp_requested is INVALID (false positive)
        // This matches the false positive case from the logs where warp_requested was never true
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, -125.4, 40.9, -350.4),
            exit: make_pos(0x0A0A1000, -119.4, 40.6, -353.5),
            transport_type: "PostBossWarp".to_string(),
            destination_entity_id: 0,
            warp_was_requested: false,
        };
        assert!(!discovery.is_valid());
    }

    #[test]
    fn test_discovery_event_liurnia_tower_door_with_warp_requested() {
        // LiurniaTowerDoor with warp_requested=true is valid
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, 100.0, 0.0, 100.0),
            exit: make_pos(0x0B0B1000, 100.0, 0.0, 100.0),
            transport_type: "LiurniaTowerDoor".to_string(),
            destination_entity_id: 0,
            warp_was_requested: true,
        };
        assert!(discovery.is_valid());
    }

    #[test]
    fn test_discovery_event_liurnia_tower_door_false_positive() {
        // LiurniaTowerDoor without warp_requested is INVALID (false positive)
        let discovery = DiscoveryEvent {
            entry: make_pos(0x0A0A1000, -90.1, 357.2, 22.1),
            exit: make_pos(0x0A0A1000, -71.6, 347.8, 16.9),
            transport_type: "LiurniaTowerDoor".to_string(),
            destination_entity_id: 0,
            warp_was_requested: false,
        };
        assert!(!discovery.is_valid());
    }

    #[test]
    fn test_post_boss_warp_filtered_in_check_warp() {
        // Full integration test: PostBossWarp false positive should not emit discovery
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A1000, -125.4, 40.9, -350.4)), // Entry
                Some(make_pos(0x0A0A1000, -125.4, 40.9, -350.4)), // Animation starts
                Some(make_pos(0x0A0A1000, -119.4, 40.6, -353.5)), // Exit (same map, ~6m)
            ],
            vec![Some(0), Some(Animation::PostBossWarp.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        // No dest_entity set (remains 0)

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Should NOT emit discovery due to false positive filtering
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(
            discovery.is_none(),
            "PostBossWarp false positive should be filtered"
        );
    }

    #[test]
    fn test_post_boss_warp_valid_with_warp_requested() {
        // PostBossWarp with warp_requested=true should emit discovery
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A101000, 100.0, 0.0, 100.0)), // Boss arena
                Some(make_pos(0x0A101000, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x3C5A0000, 200.0, 0.0, 200.0)), // Different map
            ],
            vec![Some(0), Some(Animation::PostBossWarp.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        // Set warp_requested=true to indicate a real warp
        warp.set_warp(true, 0, 0x3C5A0000);

        let mut tracker = WarpTracker::new();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(
            discovery.is_some(),
            "PostBossWarp with warp_requested should be valid"
        );
        assert_eq!(discovery.unwrap().transport_type, "PostBossWarp");
    }
}
