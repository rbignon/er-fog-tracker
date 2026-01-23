//! Warp tracking state machine
//!
//! This module contains the core logic for detecting fog gate traversals.
//! It is platform-independent and can be tested without Windows APIs.
//!
//! # Detection Strategy
//!
//! The tracker uses multiple triggers to detect warps:
//!
//! 1. **Animation trigger**: Detects known teleport animations (fog walls, waygates, etc.)
//! 2. **Fog Rando trigger**: Detects Fog Gate Randomizer entities (755890xxx range)
//!    even with unknown animations
//!
//! Each trigger can create a pending warp, which is then completed when the
//! player arrives at the destination (animation ends + position readable).

use std::time::Instant;

use super::animations::{get_teleport_type, is_fog_or_waygate_animation};
use super::constants::WARP_TIMEOUT;
use super::entity_utils::is_fog_rando_entity;
use super::traits::{GameStateReader, WarpDetector};
use super::types::PlayerPosition;

// =============================================================================
// FRAME STATE
// =============================================================================

/// Snapshot of game state for the current frame.
///
/// This struct encapsulates all the data needed to evaluate triggers and
/// update the warp tracker state. It's created once per frame and passed
/// to the various evaluation methods.
#[derive(Debug)]
struct FrameState {
    /// Current player position (None if loading)
    position: Option<PlayerPosition>,
    /// Current animation ID
    cur_anim: Option<u32>,
    /// Whether the current animation is a known teleport animation
    is_teleport_anim: bool,
    /// Transport type inferred from animation (e.g., "FogWall", "Waygate")
    transport_type: String,
    /// Whether warp_requested flag is true
    warp_requested: bool,
    /// Destination entity ID from warp detector
    dest_entity_id: u32,
    /// Target grace entity ID (non-zero for Fast Travel)
    target_grace: u32,
}

impl FrameState {
    /// Create a FrameState by reading from game state and warp detector.
    fn from_game<G: GameStateReader, W: WarpDetector>(game_state: &G, warp_detector: &W) -> Self {
        let position = game_state.read_position();
        let cur_anim = game_state.read_animation();
        let teleport_type = cur_anim.and_then(get_teleport_type);

        Self {
            position,
            cur_anim,
            is_teleport_anim: teleport_type.is_some(),
            transport_type: teleport_type.unwrap_or_else(|| "UNKNOWN".to_string()),
            warp_requested: warp_detector.is_warp_requested(),
            dest_entity_id: warp_detector.get_destination_entity_id(),
            target_grace: warp_detector.get_target_grace_entity_id(),
        }
    }

    /// Whether the position is readable (not in loading screen).
    fn position_readable(&self) -> bool {
        self.position.is_some()
    }

    /// Check if this frame represents a Fast Travel.
    ///
    /// Fast Travel is detected when:
    /// - target_grace is non-zero (grace selected in map)
    /// - Current animation is NOT a fog/waygate (those override fast travel)
    fn is_fast_travel(&self) -> bool {
        let is_fog_or_waygate = self.cur_anim.is_some_and(is_fog_or_waygate_animation);
        self.target_grace != 0 && !is_fog_or_waygate
    }
}

// =============================================================================
// TRIGGER SOURCE
// =============================================================================

/// Source that triggered the creation of a pending warp.
///
/// This enum makes explicit which detection mechanism created the pending warp,
/// which determines the transport_type and logging behavior.
#[derive(Debug, Clone, Copy, PartialEq)]
enum TriggerSource {
    /// Triggered by a known teleport animation (fog wall, waygate, etc.)
    Animation,
    /// Triggered by a Fog Gate Randomizer entity ID (755890xxx range)
    FogRando,
    /// Triggered by a vanilla warp (coffins, scripted teleports) with no known animation
    VanillaWarp,
}

impl TriggerSource {
    /// Get the transport type for this trigger.
    ///
    /// For Animation triggers, the transport type comes from the frame's detected animation.
    /// For FogRando/VanillaWarp triggers, it's a fixed string since the animation is unknown.
    fn transport_type(self, frame: &FrameState) -> String {
        match self {
            TriggerSource::Animation => frame.transport_type.clone(),
            TriggerSource::FogRando => "FOG_RANDO".to_string(),
            TriggerSource::VanillaWarp => "VANILLA_WARP".to_string(),
        }
    }
}

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

/// Core warp tracking state machine.
///
/// Call `check_warp` every frame to detect fog gate traversals.
/// See module documentation for the detection strategy.
pub struct WarpTracker {
    /// Pending warp (entry recorded, waiting for exit)
    pending_warp: Option<PendingWarp>,
    /// Whether we were in a teleport animation last frame
    was_in_teleport_anim: bool,
    /// Whether position was readable last frame (to detect loading screens)
    was_position_readable: bool,
    /// Whether warp_requested was true last frame (to detect transition)
    was_warp_requested: bool,
}

impl WarpTracker {
    /// Create a new WarpTracker.
    pub fn new() -> Self {
        Self {
            pending_warp: None,
            was_in_teleport_anim: false,
            was_position_readable: false,
            was_warp_requested: false,
        }
    }

    // =========================================================================
    // Public API
    // =========================================================================

    /// Check for fog gate traversals.
    ///
    /// Call this every frame. Returns a `DiscoveryEvent` if a warp was completed.
    pub fn check_warp<G: GameStateReader, W: WarpDetector>(
        &mut self,
        game_state: &G,
        warp_detector: &W,
    ) -> Option<DiscoveryEvent> {
        // 1. Gather frame state
        let frame = FrameState::from_game(game_state, warp_detector);

        // 2. Expire timed-out pending warps
        self.expire_timed_out_pending();

        // 3. Evaluate triggers and create pending if needed
        if let Some(source) = self.evaluate_triggers(&frame) {
            self.create_pending_from_trigger(source, &frame);
        }

        // 4. Update pending state (warp_requested, dest_entity_id, fast travel detection)
        self.update_pending_state(&frame);

        // 5. Try to complete the warp
        let discovery = self.try_complete_warp(&frame);

        // 6. Save frame state for next iteration
        self.save_frame_state(&frame);

        // 7. Filter invalid discoveries and return
        self.filter_and_log_discovery(discovery)
    }

    /// Check if we just exited a loading screen (for zone query).
    ///
    /// Returns true if position went from unreadable to readable and
    /// there's no pending warp (to avoid querying when we'll get info from discovery).
    pub fn just_exited_loading_screen<G: GameStateReader>(&self, game_state: &G) -> bool {
        let position_now_readable = game_state.read_position().is_some();
        position_now_readable && !self.was_position_readable && self.pending_warp.is_none()
    }

    /// Get the current pending warp, if any.
    pub fn pending_warp(&self) -> Option<&PendingWarp> {
        self.pending_warp.as_ref()
    }

    /// Check if there's a pending warp.
    pub fn has_pending_warp(&self) -> bool {
        self.pending_warp.is_some()
    }

    /// Clear the pending warp (for testing or error recovery).
    pub fn clear_pending_warp(&mut self) {
        self.pending_warp = None;
    }

    // =========================================================================
    // Timeout handling
    // =========================================================================

    /// Clear pending warp if it has timed out.
    ///
    /// Pendings with `warp_was_requested=true` are never expired: they represent
    /// a real warp in progress (e.g., loading screen after a waygate). Timing out
    /// such a pending would cause the discovery to be lost.
    fn expire_timed_out_pending(&mut self) {
        if self
            .pending_warp
            .as_ref()
            .is_some_and(|p| p.is_timed_out() && !p.warp_was_requested)
        {
            self.pending_warp = None;
        }
    }

    // =========================================================================
    // Trigger evaluation
    // =========================================================================

    /// Evaluate all triggers and return which one fired, if any.
    ///
    /// Triggers are evaluated in priority order. Only one can fire per frame.
    fn evaluate_triggers(&self, frame: &FrameState) -> Option<TriggerSource> {
        // Animation trigger has priority (more specific transport type)
        if let Some(source) = self.check_animation_trigger(frame) {
            return Some(source);
        }

        // Fog Rando entity trigger (catches unknown animations with fog rando entity)
        if let Some(source) = self.check_fog_rando_trigger(frame) {
            return Some(source);
        }

        // Vanilla warp trigger (catches coffins, scripted teleports with vanilla entity)
        if let Some(source) = self.check_vanilla_warp_trigger(frame) {
            return Some(source);
        }

        None
    }

    /// Check if animation trigger should fire.
    ///
    /// Fires when:
    /// - A known teleport animation just started
    /// - There's no active warp in progress (warp_was_requested=true)
    fn check_animation_trigger(&self, frame: &FrameState) -> Option<TriggerSource> {
        let animation_just_started = frame.is_teleport_anim && !self.was_in_teleport_anim;
        let has_active_warp = self
            .pending_warp
            .as_ref()
            .is_some_and(|p| p.warp_was_requested);

        if animation_just_started && !has_active_warp {
            Some(TriggerSource::Animation)
        } else {
            None
        }
    }

    /// Check if Fog Rando entity trigger should fire.
    ///
    /// Fires when:
    /// - warp_requested just became true
    /// - dest_entity_id is in Fog Rando range (755890xxx)
    /// - No pending warp exists
    fn check_fog_rando_trigger(&self, frame: &FrameState) -> Option<TriggerSource> {
        let warp_just_requested = frame.warp_requested && !self.was_warp_requested;

        if warp_just_requested
            && is_fog_rando_entity(frame.dest_entity_id)
            && self.pending_warp.is_none()
        {
            Some(TriggerSource::FogRando)
        } else {
            None
        }
    }

    /// Check if vanilla warp trigger should fire.
    ///
    /// Fires when:
    /// - warp_requested just became true
    /// - dest_entity_id is NOT in Fog Rando range (already handled by Trigger B)
    /// - dest_entity_id != 0 (not death/respawn/remembrance)
    /// - target_grace == 0 (not fast travel)
    /// - No pending warp exists
    ///
    /// This catches vanilla warps like coffins (e.g., after Valiant Gargoyles)
    /// that have no distinctive animation.
    fn check_vanilla_warp_trigger(&self, frame: &FrameState) -> Option<TriggerSource> {
        let warp_just_requested = frame.warp_requested && !self.was_warp_requested;

        if warp_just_requested
            && !is_fog_rando_entity(frame.dest_entity_id)
            && frame.dest_entity_id != 0
            && frame.target_grace == 0
            && self.pending_warp.is_none()
        {
            Some(TriggerSource::VanillaWarp)
        } else {
            None
        }
    }

    /// Create a pending warp from the trigger that fired.
    fn create_pending_from_trigger(&mut self, source: TriggerSource, frame: &FrameState) {
        let Some(pos) = frame.position.clone() else {
            // Can't create pending without entry position
            if matches!(source, TriggerSource::Animation) {
                tracing::warn!(
                    transport_type = frame.transport_type,
                    "[WARP] Animation trigger but position=None - pending NOT created!"
                );
            }
            return;
        };

        let transport_type = source.transport_type(frame);
        let (dest_entity_id, warp_was_requested) = match source {
            TriggerSource::Animation => {
                tracing::debug!(
                    transport_type = transport_type,
                    map = pos.map_id_str,
                    pos = format!("({:.1}, {:.1}, {:.1})", pos.x, pos.y, pos.z),
                    "[WARP] Pending created by animation trigger"
                );
                (0, false)
            }
            TriggerSource::FogRando => {
                tracing::debug!(
                    dest_entity = frame.dest_entity_id,
                    map = pos.map_id_str,
                    "[WARP] Pending created by Fog Rando trigger"
                );
                (frame.dest_entity_id, true) // warp_was_requested already true since that's how we triggered
            }
            TriggerSource::VanillaWarp => {
                tracing::debug!(
                    dest_entity = frame.dest_entity_id,
                    map = pos.map_id_str,
                    "[WARP] Pending created by vanilla warp trigger"
                );
                (frame.dest_entity_id, true) // warp_was_requested already true since that's how we triggered
            }
        };

        self.pending_warp = Some(PendingWarp {
            entry: pos,
            destination_entity_id: dest_entity_id,
            transport_type,
            created_at: Instant::now(),
            warp_was_requested,
        });
    }

    // =========================================================================
    // Pending state updates
    // =========================================================================

    /// Update the pending warp state based on current frame.
    ///
    /// This handles:
    /// - Detecting Fast Travel and clearing false positive pendings
    /// - Setting warp_was_requested when warp starts
    /// - Capturing dest_entity_id when it becomes available
    fn update_pending_state(&mut self, frame: &FrameState) {
        let Some(pending) = self.pending_warp.as_mut() else {
            return;
        };

        // Check if warp_requested just became true for this pending
        if frame.warp_requested && !pending.warp_was_requested {
            if frame.is_fast_travel() {
                // Fast Travel detected - clear the false positive pending
                tracing::info!(
                    target_grace = frame.target_grace,
                    cur_anim = frame.cur_anim.unwrap_or(0),
                    pending_transport = pending.transport_type,
                    "[WARP] >>> FAST TRAVEL <<< clearing false positive pending"
                );
                self.pending_warp = None;
                return;
            }

            // Legitimate warp - mark as requested.
            // Update transport_type to the current animation if it's a teleport,
            // because the pending may have been created by an earlier animation in
            // a continuous teleport cycle (e.g., PostBossWarp cutscene before Waygate).
            if frame.is_teleport_anim && frame.transport_type != pending.transport_type {
                tracing::debug!(
                    old_transport = pending.transport_type,
                    new_transport = frame.transport_type,
                    "[WARP] transport_type updated to current animation"
                );
                pending.transport_type = frame.transport_type.clone();
            }
            tracing::debug!(
                dest_entity = frame.dest_entity_id,
                transport_type = pending.transport_type,
                "[WARP] warp_was_requested=true"
            );
            pending.warp_was_requested = true;
        }

        // Re-borrow after potential mutation
        let Some(pending) = self.pending_warp.as_mut() else {
            return;
        };

        // Capture dest_entity_id when it becomes available
        if pending.destination_entity_id == 0 && frame.dest_entity_id != 0 {
            pending.destination_entity_id = frame.dest_entity_id;
        }
    }

    // =========================================================================
    // Warp completion
    // =========================================================================

    /// Try to complete the pending warp and return a discovery event.
    ///
    /// Completion happens when:
    /// - Animation just ended and position is readable, OR
    /// - No animation playing and position just became readable (delayed completion)
    fn try_complete_warp(&mut self, frame: &FrameState) -> Option<DiscoveryEvent> {
        // Check for animation-end completion
        if let Some(discovery) = self.try_animation_end_completion(frame) {
            return Some(discovery);
        }

        // Check for delayed completion (position became readable after animation ended)
        self.try_delayed_completion(frame)
    }

    /// Try to complete warp when animation just ended.
    fn try_animation_end_completion(&mut self, frame: &FrameState) -> Option<DiscoveryEvent> {
        let animation_just_ended = !frame.is_teleport_anim && self.was_in_teleport_anim;

        if !animation_just_ended {
            return None;
        }

        let pending = self.pending_warp.take()?;

        let Some(exit_pos) = frame.position.clone() else {
            // Position not readable yet (still loading) - keep pending
            tracing::debug!(
                transport_type = pending.transport_type,
                warp_was_requested = pending.warp_was_requested,
                "[WARP] Exit detection: position=None, keeping pending"
            );
            self.pending_warp = Some(pending);
            return None;
        };

        Some(Self::complete_pending(pending, exit_pos, false))
    }

    /// Try delayed completion when position becomes readable after a loading screen.
    ///
    /// This handles cases where:
    /// - Animation ended during loading and we're now readable (Trigger A)
    /// - VanillaWarp pending created, went through loading, now readable (Trigger C)
    ///
    /// Key requirement: position must have been unreadable last frame (just exited loading).
    /// This prevents completing immediately when a pending is created.
    fn try_delayed_completion(&mut self, frame: &FrameState) -> Option<DiscoveryEvent> {
        // Only complete when exiting a loading screen (position just became readable)
        let just_exited_loading = frame.position_readable() && !self.was_position_readable;

        if frame.is_teleport_anim || !just_exited_loading {
            return None;
        }

        let pending = self.pending_warp.take()?;
        let exit_pos = frame.position.clone()?;

        Some(Self::complete_pending(pending, exit_pos, true))
    }

    /// Create a DiscoveryEvent from a completed pending warp.
    fn complete_pending(
        pending: PendingWarp,
        exit_pos: PlayerPosition,
        delayed: bool,
    ) -> DiscoveryEvent {
        let suffix = if delayed { " (delayed)" } else { "" };
        tracing::info!(
            transport_type = pending.transport_type,
            entry_map = pending.entry.map_id_str,
            exit_map = exit_pos.map_id_str,
            dest_entity = pending.destination_entity_id,
            warp_was_requested = pending.warp_was_requested,
            "[WARP] >>> EXIT DETECTED{suffix} <<<"
        );

        DiscoveryEvent {
            entry: pending.entry,
            exit: exit_pos,
            transport_type: pending.transport_type,
            destination_entity_id: pending.destination_entity_id,
            warp_was_requested: pending.warp_was_requested,
        }
    }

    // =========================================================================
    // Frame state management
    // =========================================================================

    /// Save current frame state for comparison in next frame.
    fn save_frame_state(&mut self, frame: &FrameState) {
        self.was_in_teleport_anim = frame.is_teleport_anim;
        self.was_position_readable = frame.position_readable();
        self.was_warp_requested = frame.warp_requested;
    }

    /// Filter invalid discoveries and log filtered ones for debugging.
    fn filter_and_log_discovery(
        &self,
        discovery: Option<DiscoveryEvent>,
    ) -> Option<DiscoveryEvent> {
        let discovery = discovery?;

        if !discovery.is_valid() {
            tracing::warn!(
                transport_type = discovery.transport_type,
                warp_was_requested = discovery.warp_was_requested,
                dest_entity = discovery.destination_entity_id,
                entry_map = discovery.entry.map_id_str,
                exit_map = discovery.exit.map_id_str,
                "[WARP] !!! FILTERED (warp_was_requested=false) !!!"
            );
            return None;
        }

        Some(discovery)
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

    // =========================================================================
    // Bug fix tests: Fast Travel detection and pending protection
    // =========================================================================

    #[test]
    fn test_fast_travel_clears_false_positive_pending() {
        // Scenario: Player is in a zone, an animation like LiurniaDivineTower creates
        // a pending, then they Fast Travel. The pending should be cleared, not used.
        //
        // Timeline from bug:
        // - LiurniaDivineTower animation creates pending at m16_00_00_00
        // - Fast Travel initiated with target_grace=14002955, cur_anim=WayToMetyr (not fog/waygate)
        // - Expected: pending cleared, no discovery sent
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // Initial position
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // LiurniaDivineTower starts
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // Still in animation
                Some(make_pos(0x10000000, 100.0, 0.0, 100.0)), // Fast Travel initiated (no teleport anim)
                None,                                          // Loading
                Some(make_pos(0x0E000000, 200.0, 0.0, 200.0)), // Arrived at grace
            ],
            vec![
                Some(0),
                Some(Animation::LiurniaDivineTower.as_u32()), // Creates pending
                Some(Animation::LiurniaDivineTower.as_u32()),
                Some(0), // Animation ended, Fast Travel starts (no teleport anim playing)
                Some(0),
                Some(0),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: LiurniaDivineTower animation starts - creates pending
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp(), "Pending should be created");
        game_state.advance_frame();

        // Frame 2: Still in animation
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 3: Animation ended. Fast Travel initiated with target_grace.
        // cur_anim=0 (no teleport animation), so this should be detected as Fast Travel.
        warp.set_warp(true, 14000985, 0x0E000000);
        warp.set_target_grace(14002955); // Non-zero = Fast Travel
        let discovery = tracker.check_warp(&game_state, &warp);

        // The pending should have been cleared because:
        // - target_grace != 0
        // - cur_anim (0) is not a fog/waygate animation
        assert!(
            discovery.is_none(),
            "Fast Travel should not trigger discovery from stale pending"
        );
        assert!(
            !tracker.has_pending_warp(),
            "Pending should be cleared on Fast Travel"
        );
    }

    #[test]
    fn test_waygate_with_target_grace_still_works() {
        // Scenario: Player has a target_grace set (from previous menu interaction),
        // but they use a Waygate instead of completing the fast travel.
        // The Waygate should still be tracked because cur_anim IS a fog/waygate.
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0E000000, 100.0, 0.0, 100.0)), // Start
                Some(make_pos(0x0E000000, 100.0, 0.0, 100.0)), // Waygate animation
                Some(make_pos(0x0C040000, 200.0, 0.0, 200.0)), // Arrived via waygate
            ],
            vec![Some(0), Some(Animation::Waygate.as_u32()), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Waygate animation starts
        // Even with target_grace set, Waygate should be tracked
        warp.set_warp(true, 755890123, 0x0C040000);
        warp.set_target_grace(14002955); // Has target_grace but cur_anim is Waygate
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert!(
            tracker.pending_warp().unwrap().warp_was_requested,
            "warp_was_requested should be set for Waygate even with target_grace"
        );
        game_state.advance_frame();

        // Frame 2: Waygate completes
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(
            discovery.is_some(),
            "Waygate should emit discovery even with target_grace set"
        );
        assert_eq!(discovery.unwrap().transport_type, "Waygate");
    }

    #[test]
    fn test_pending_not_overwritten_when_warp_in_progress() {
        // Scenario: Player uses a Waygate, warp_was_requested becomes true,
        // then during loading a new animation plays on the destination map.
        // The new animation should NOT overwrite the pending.
        //
        // Timeline from bug:
        // - PostBossWarp pending created, warp_was_requested=true set
        // - After loading, WayToMetyr animation on new map
        // - Previously: new pending created, warp_was_requested=false, discovery filtered
        // - Now: pending preserved, discovery sent
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0E000000, 100.0, 0.0, 100.0)), // Start
                Some(make_pos(0x0E000000, 100.0, 0.0, 100.0)), // Waygate animation
                None,                                          // Loading
                Some(make_pos(0x0C040000, 200.0, 0.0, 200.0)), // Arrived, PostBossWarp plays
                Some(make_pos(0x0C040000, 200.0, 0.0, 200.0)), // PostBossWarp ends
            ],
            vec![
                Some(0),
                Some(Animation::Waygate.as_u32()),
                Some(Animation::Waygate.as_u32()), // Still in animation during load
                Some(Animation::PostBossWarp.as_u32()), // New animation on dest map
                Some(0),                           // Animation ends
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Waygate animation starts, warp requested
        warp.set_warp(true, 755890100, 0x0C040000);
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert!(tracker.pending_warp().unwrap().warp_was_requested);
        assert_eq!(tracker.pending_warp().unwrap().transport_type, "Waygate");
        game_state.advance_frame();

        // Frame 2: Loading (position=None)
        tracker.check_warp(&game_state, &warp);
        assert!(
            tracker.has_pending_warp(),
            "Pending should be kept during loading"
        );
        game_state.advance_frame();

        // Frame 3: Arrived, PostBossWarp animation plays
        // This should NOT create a new pending because existing has warp_was_requested=true
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "Waygate",
            "Pending should still be the original Waygate, not overwritten by PostBossWarp"
        );
        game_state.advance_frame();

        // Frame 4: PostBossWarp ends - discovery should trigger with Waygate transport type
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some(), "Discovery should be emitted");
        let d = discovery.unwrap();
        assert_eq!(
            d.transport_type, "Waygate",
            "Transport type should be Waygate from original pending"
        );
        assert!(d.warp_was_requested);
    }

    #[test]
    fn test_sending_gate_with_loading_and_animation_on_arrival() {
        // Full scenario test: Sending gate traversal with loading screen,
        // then an animation plays on the destination map.
        //
        // This tests the fix for the bug where:
        // 1. Waygate pending created
        // 2. Warp requested, warp_was_requested=true
        // 3. Loading (position=None), pending kept
        // 4. New animation on dest map tried to create new pending
        // 5. Previously: new pending had warp_was_requested=false, filtered
        // 6. Now: pending protected, discovery sent correctly
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0E000000, 150.0, 128.0, -60.0)), // Academy area
                Some(make_pos(0x0E000000, 150.0, 128.0, -60.0)), // Waygate starts
                None,                                            // Loading
                None,                                            // Still loading
                Some(make_pos(0x0C040000, -90.0, -104.0, -330.0)), // Before Astel
                Some(make_pos(0x0C040000, -90.0, -104.0, -330.0)), // LiurniaDivineTower plays
                Some(make_pos(0x0C040000, -90.0, -104.0, -330.0)), // Animation ends
            ],
            vec![
                Some(0),
                Some(Animation::Waygate.as_u32()),
                Some(Animation::Waygate.as_u32()),
                Some(0), // Animation might be unreadable during load
                Some(Animation::LiurniaDivineTower.as_u32()), // Animation on arrival
                Some(Animation::LiurniaDivineTower.as_u32()),
                Some(0),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle at Academy
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Waygate animation starts
        warp.set_warp(true, 12042506, 0x0C040000);
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert_eq!(tracker.pending_warp().unwrap().transport_type, "Waygate");
        assert!(tracker.pending_warp().unwrap().warp_was_requested);
        game_state.advance_frame();

        // Frame 2: Loading
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 3: Still loading
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp(), "Pending kept during loading");
        game_state.advance_frame();

        // Frame 4: Arrived, LiurniaDivineTower animation starts
        // Pending should NOT be overwritten
        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "Waygate",
            "Original Waygate pending should be preserved"
        );
        game_state.advance_frame();

        // Frame 5: Still in LiurniaDivineTower
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 6: Animation ends - discovery
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some(), "Discovery should be emitted");
        let d = discovery.unwrap();
        assert_eq!(d.entry.map_id, 0x0E000000, "Entry should be Academy");
        assert_eq!(d.exit.map_id, 0x0C040000, "Exit should be Astel area");
        assert_eq!(d.transport_type, "Waygate");
        assert!(d.is_valid(), "Discovery should be valid");
    }

    #[test]
    fn test_vanilla_warp_coffin_after_gargoyles() {
        // Test case: Coffin after Valiant Gargoyles
        // - Animation 3000000 (idle) is not a known teleport animation
        // - Entity 12092400 is not in Fog Rando range
        // - warp_requested becomes true with target_grace=0
        // - Trigger C (VanillaWarp) should fire
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0C050000, 100.0, 50.0, 200.0)), // Before coffin
                Some(make_pos(0x0C050000, 100.0, 50.0, 200.0)), // Entering coffin
                None,                                           // Loading
                Some(make_pos(0x0C060000, -50.0, 100.0, 150.0)), // Deeproot Depths
            ],
            vec![
                Some(0),       // Idle
                Some(3000000), // Coffin animation (idle-like, not a known teleport)
                Some(3000000),
                Some(0), // After loading
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: warp_requested becomes true with vanilla entity (not fog rando)
        // Animation 3000000 is not a known teleport, so Trigger A doesn't fire
        // Entity 12092400 is not in 755890xxx range, so Trigger B doesn't fire
        // But: warp_requested=true, dest_entity!=0, target_grace=0 → Trigger C fires
        warp.set_warp(true, 12092400, 0x0C060000); // Vanilla entity
        let result = tracker.check_warp(&game_state, &warp);
        assert!(result.is_none(), "No discovery yet");
        assert!(
            tracker.has_pending_warp(),
            "Pending should be created by VanillaWarp trigger"
        );
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "VANILLA_WARP"
        );
        assert_eq!(
            tracker.pending_warp().unwrap().destination_entity_id,
            12092400
        );
        game_state.advance_frame();

        // Frame 2: Loading
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 3: Arrived at Deeproot Depths
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some(), "Discovery should be emitted");
        let d = discovery.unwrap();
        assert_eq!(d.transport_type, "VANILLA_WARP");
        assert_eq!(d.destination_entity_id, 12092400);
        assert_eq!(d.entry.map_id, 0x0C050000);
        assert_eq!(d.exit.map_id, 0x0C060000);
        assert!(d.is_valid(), "VanillaWarp discovery should be valid");
    }

    #[test]
    fn test_vanilla_warp_not_triggered_for_fast_travel() {
        // Ensure Trigger C doesn't fire when target_grace != 0 (fast travel)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
            ],
            vec![Some(0), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: warp_requested with target_grace (fast travel)
        warp.set_warp(true, 12345678, 0x0B0B0000);
        warp.set_target_grace(1042362951);
        tracker.check_warp(&game_state, &warp);
        assert!(
            !tracker.has_pending_warp(),
            "No pending should be created for fast travel"
        );
    }

    #[test]
    fn test_vanilla_warp_not_triggered_for_death() {
        // Ensure Trigger C doesn't fire when dest_entity_id == 0 (death/respawn)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
            ],
            vec![Some(0), Some(0)],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: warp_requested with dest_entity=0 (death/respawn)
        warp.set_warp(true, 0, 0x0B0B0000);
        tracker.check_warp(&game_state, &warp);
        assert!(
            !tracker.has_pending_warp(),
            "No pending should be created for death/respawn"
        );
    }

    #[test]
    fn test_vanilla_warp_blocked_by_fog_rando() {
        // Ensure Fog Rando trigger (B) takes priority over VanillaWarp trigger (C)
        // when dest_entity is in Fog Rando range
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
            ],
            vec![Some(0), Some(0)], // No known teleport animation
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: warp_requested with Fog Rando entity (755890xxx range)
        warp.set_warp(true, 755890123, 0x0B0B0000);
        tracker.check_warp(&game_state, &warp);

        // Fog Rando trigger should win, not VanillaWarp
        assert!(tracker.has_pending_warp());
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "FOG_RANDO",
            "Fog Rando trigger should take priority over VanillaWarp"
        );
    }

    #[test]
    fn test_waygate_after_continuous_teleport_cycle() {
        // Bug reproduction: Divine Tower of Limgrave plays continuous teleport
        // animations (PostBossWarp, LiurniaDivineTower, BurningScalingTree) as
        // cutscene effects. The player takes a Waygate during this cycle.
        //
        // Previously:
        // - PostBossWarp created a pending early in the cycle
        // - All subsequent anims were teleport→teleport (no new pending)
        // - Pending accumulated 28+ seconds before the warp started
        // - Pending timed out (30s) during the loading screen
        // - No discovery was produced
        //
        // Fix 1: Don't timeout pending with warp_was_requested=true
        // Fix 2: Update transport_type to current anim when warp_was_requested becomes true
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)), // Divine Tower
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)), // PostBossWarp starts
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)), // LiurniaDivineTower
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)), // Waygate
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)), // Waygate + warp_requested
                None,                                              // Loading
                None,                                              // Still loading
                Some(make_pos(0x0A_01_00_00, 22.8, 13.2, 2.3)),    // Arrived
            ],
            vec![
                Some(0),                                      // Idle
                Some(Animation::PostBossWarp.as_u32()),       // Cutscene animation
                Some(Animation::LiurniaDivineTower.as_u32()), // Another cutscene anim
                Some(Animation::Waygate.as_u32()),            // Player takes waygate
                Some(Animation::Waygate.as_u32()),            // Still in waygate
                Some(Animation::Waygate.as_u32()),            // During loading
                Some(0),                                      // Animation unreadable
                Some(0),                                      // Arrived
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: PostBossWarp starts - creates pending
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "PostBossWarp"
        );
        game_state.advance_frame();

        // Frame 2: LiurniaDivineTower (teleport→teleport, no new pending)
        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "PostBossWarp"
        );
        game_state.advance_frame();

        // Frame 3: Waygate (teleport→teleport, no new pending)
        tracker.check_warp(&game_state, &warp);
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "PostBossWarp"
        );
        game_state.advance_frame();

        // Simulate pending being 28s old (warp_requested fires before 30s timeout)
        if let Some(ref mut pending) = tracker.pending_warp {
            pending.created_at = Instant::now() - Duration::from_secs(28);
        }

        // Frame 4: warp_requested becomes true (player entered waygate)
        warp.set_warp(true, 10012690, 0x0A_01_00_00);
        tracker.check_warp(&game_state, &warp);

        // Fix 2: transport_type should be updated to Waygate (current animation)
        assert!(tracker.has_pending_warp(), "Pending should still exist");
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type, "Waygate",
            "transport_type should be updated to current animation when warp_was_requested becomes true"
        );
        assert!(tracker.pending_warp().unwrap().warp_was_requested);
        game_state.advance_frame();

        // Now simulate the pending being >30s old (loading takes several seconds)
        if let Some(ref mut pending) = tracker.pending_warp {
            pending.created_at = Instant::now() - Duration::from_secs(35);
        }

        // Frame 5: Loading (position=None, animation still readable)
        // Fix 1: pending should NOT timeout despite being >30s old
        tracker.check_warp(&game_state, &warp);
        assert!(
            tracker.has_pending_warp(),
            "Pending with warp_was_requested=true should NOT timeout"
        );
        game_state.advance_frame();

        // Frame 6: Still loading, animation unreadable
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        game_state.advance_frame();

        // Frame 7: Arrived - delayed completion
        let discovery = tracker.check_warp(&game_state, &warp);
        assert!(discovery.is_some(), "Discovery should be produced");
        let d = discovery.unwrap();
        assert_eq!(
            d.transport_type, "Waygate",
            "Should be Waygate, not PostBossWarp"
        );
        assert_eq!(d.destination_entity_id, 10012690);
        assert!(d.warp_was_requested);
        assert!(d.is_valid());
    }

    #[test]
    fn test_timeout_still_works_without_warp_requested() {
        // Verify that timeout still clears false positive pendings (warp_was_requested=false)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)),
                Some(make_pos(0x22_0A_00_00, 100.0, 50.0, 200.0)),
            ],
            vec![Some(0), Some(Animation::PostBossWarp.as_u32())],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: PostBossWarp creates pending (no warp_requested)
        tracker.check_warp(&game_state, &warp);
        assert!(tracker.has_pending_warp());
        assert!(!tracker.pending_warp().unwrap().warp_was_requested);

        // Simulate timeout
        if let Some(ref mut pending) = tracker.pending_warp {
            pending.created_at = Instant::now() - Duration::from_secs(35);
        }

        // Next check_warp should expire it
        tracker.check_warp(&game_state, &warp);
        assert!(
            !tracker.has_pending_warp(),
            "Pending without warp_was_requested should still timeout"
        );
    }

    #[test]
    fn test_vanilla_warp_blocked_by_animation() {
        // Ensure Animation trigger (A) takes priority over VanillaWarp trigger (C)
        // when a known teleport animation is playing
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
                Some(make_pos(0x0A0A0000, 100.0, 50.0, 200.0)),
            ],
            vec![
                Some(0),
                Some(Animation::FogWall.as_u32()), // Known teleport animation
            ],
        );

        let warp = MockWarpDetector::new();
        let mut tracker = WarpTracker::new();

        // Frame 0: Idle
        tracker.check_warp(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: FogWall animation + warp_requested with vanilla entity
        warp.set_warp(true, 12345678, 0x0B0B0000); // Vanilla entity (not fog rando)
        tracker.check_warp(&game_state, &warp);

        // Animation trigger should win, not VanillaWarp
        assert!(tracker.has_pending_warp());
        assert_eq!(
            tracker.pending_warp().unwrap().transport_type,
            "FogWall",
            "Animation trigger should take priority over VanillaWarp"
        );
    }
}
