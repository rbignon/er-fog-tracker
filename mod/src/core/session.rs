//! Tracker session - orchestrates warp tracking with server communication
//!
//! TrackerSession combines WarpTracker with I/O traits to provide
//! the complete fog gate tracking logic, testable on any platform.

use crate::core::io_traits::{
    ConnectionStatus, DiscoveryResult, DiscoverySender, ServerEvent, ServerEventReceiver,
    ZoneQueryResult,
};
use crate::core::protocol::{DiscoveryStats, FogExit};
use crate::core::traits::{GameStateReader, WarpDetector};
use crate::core::warp_tracker::{DiscoveryEvent, WarpTracker};
use tracing::debug;

// =============================================================================
// SESSION EVENTS
// =============================================================================

/// Events emitted by TrackerSession for UI updates and logging
#[derive(Debug, Clone, PartialEq)]
pub enum SessionEvent {
    /// A discovery was sent to the server
    DiscoverySent(DiscoveryEvent),
    /// Server acknowledged a discovery
    DiscoveryAcked(DiscoveryResult),
    /// A zone query was sent to the server
    ZoneQuerySent,
    /// Zone query response received
    ZoneUpdated(ZoneQueryResult),
    /// Connection status changed
    ConnectionChanged(ConnectionStatus),
    /// Log upload result received
    LogsUploaded {
        success: bool,
        message: Option<String>,
    },
    /// Server error occurred
    ServerError(String),
    /// Stats updated (on reconnection, without zone/exits reset)
    StatsUpdated(DiscoveryStats),
}

// =============================================================================
// SESSION STATE
// =============================================================================

/// Session state updated from server responses
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SessionState {
    /// Current zone name
    pub current_zone: Option<String>,
    /// Zone key (e.g., "limgrave_stormhill")
    pub current_zone_id: Option<String>,
    /// Available exits from current zone
    pub exits: Vec<FogExit>,
    /// Discovery statistics
    pub stats: Option<DiscoveryStats>,
    /// Current zone scaling text (e.g., "Scaling: tier 1, previously 2")
    pub current_zone_scaling: Option<String>,
}

// =============================================================================
// TRACKER SESSION
// =============================================================================

/// TrackerSession orchestrates WarpTracker with server I/O
///
/// This struct manages the full tracking lifecycle:
/// 1. Warp detection via WarpTracker
/// 2. Sending discoveries to the server
/// 3. Sending zone queries after loading screens
/// 4. Processing server responses and updating state
///
/// The session is platform-independent and can be tested with mocks.
pub struct TrackerSession {
    warp_tracker: WarpTracker,
    state: SessionState,
    /// Captured target grace entity ID (only valid during fast travel)
    /// We capture this when warp_requested becomes true because it gets cleared after
    captured_target_grace: Option<u32>,
    /// Whether a warp was in progress last frame (to detect warp start)
    was_warp_requested: bool,
    /// Last known map_id when position was readable (for respawn fallback)
    /// Updated every frame when position is readable
    last_known_map_id: Option<u32>,
    /// Map ID before the loading screen (captured when zone_query is sent)
    /// Used for same-map fallback comparison
    pre_loading_map_id: Option<u32>,
}

impl TrackerSession {
    /// Create a new tracker session
    pub fn new() -> Self {
        Self {
            warp_tracker: WarpTracker::new(),
            state: SessionState::default(),
            captured_target_grace: None,
            was_warp_requested: false,
            last_known_map_id: None,
            pre_loading_map_id: None,
        }
    }

    /// Get current session state
    pub fn state(&self) -> &SessionState {
        &self.state
    }

    /// Get current zone name
    pub fn current_zone(&self) -> Option<&str> {
        self.state.current_zone.as_deref()
    }

    /// Get current zone key
    pub fn current_zone_id(&self) -> Option<&str> {
        self.state.current_zone_id.as_deref()
    }

    /// Get available exits from current zone
    pub fn exits(&self) -> &[FogExit] {
        &self.state.exits
    }

    /// Get discovery statistics
    pub fn stats(&self) -> Option<&DiscoveryStats> {
        self.state.stats.as_ref()
    }

    /// Get current zone scaling text
    pub fn current_zone_scaling(&self) -> Option<&str> {
        self.state.current_zone_scaling.as_deref()
    }

    /// Check if there's a pending warp
    pub fn has_pending_warp(&self) -> bool {
        self.warp_tracker.has_pending_warp()
    }

    /// Clear pending warp (for error recovery)
    pub fn clear_pending_warp(&mut self) {
        self.warp_tracker.clear_pending_warp();
    }

    /// Synchronize internal state without sending any events
    ///
    /// This is useful for tests or when starting the session mid-game.
    /// It updates the internal "previous frame" state to match the current
    /// game state, preventing spurious zone queries on the first update.
    pub fn sync_state<G: GameStateReader, W: WarpDetector>(
        &mut self,
        game_state: &G,
        warp_detector: &W,
    ) {
        // Do a dry run of check_warp to sync internal state
        // This updates was_position_readable and was_in_teleport_anim
        let _ = self.warp_tracker.check_warp(game_state, warp_detector);
        // Also sync warp_requested state
        self.was_warp_requested = warp_detector.is_warp_requested();
    }

    /// Update tracker each frame
    ///
    /// This method should be called every frame. It:
    /// 1. Checks for completed warps and sends discoveries
    /// 2. Detects loading screen exits and sends zone queries
    /// 3. Processes server events and updates state
    ///
    /// Returns a list of events that occurred (for logging, UI updates, etc.)
    pub fn update<G, W, S>(
        &mut self,
        game_state: &G,
        warp_detector: &W,
        server: &mut S,
    ) -> Vec<SessionEvent>
    where
        G: GameStateReader,
        W: WarpDetector,
        S: DiscoverySender + ServerEventReceiver,
    {
        let mut events = Vec::new();

        // 0. Capture target_grace when warp starts (it gets cleared after the warp)
        let warp_requested = warp_detector.is_warp_requested();
        if warp_requested && !self.was_warp_requested {
            // Warp just started - capture target grace
            let target = warp_detector.get_target_grace_entity_id();
            self.captured_target_grace = if target != 0 { Some(target) } else { None };
        }
        self.was_warp_requested = warp_requested;

        // 1. Check for loading screen exit BEFORE check_warp (which updates state)
        // This must be done first because check_warp updates was_position_readable
        let just_exited_loading = self.warp_tracker.just_exited_loading_screen(game_state);

        // 2. Check for warp completion
        if let Some(discovery) = self.warp_tracker.check_warp(game_state, warp_detector) {
            if server.is_connected() {
                // Pass cached source zone info for disambiguation
                server.send_discovery(
                    &discovery,
                    self.state.current_zone.as_deref(),
                    self.state.current_zone_id.as_deref(),
                );
                events.push(SessionEvent::DiscoverySent(discovery));
            }
        }

        // 3. Send zone query if we just exited a loading screen (without a pending warp)
        if just_exited_loading {
            if server.is_connected() {
                if let Some(pos) = game_state.read_position() {
                    // Use captured target_grace from when the warp started
                    let grace_entity_id = self.captured_target_grace.take();
                    server.send_zone_query(&pos, grace_entity_id);
                    // Capture pre-loading map_id for same-map fallback comparison
                    // (last_known_map_id still contains the map_id from before loading)
                    self.pre_loading_map_id = self.last_known_map_id;
                    events.push(SessionEvent::ZoneQuerySent);
                }
            }
        }

        // Update last_known_map_id when position is readable (after zone_query logic)
        if let Some(pos) = game_state.read_position() {
            self.last_known_map_id = Some(pos.map_id);
        }

        // 4. Poll and process server events
        while let Some(event) = server.poll_event() {
            match event {
                ServerEvent::StatusChanged(status) => {
                    events.push(SessionEvent::ConnectionChanged(status));
                }
                ServerEvent::DiscoveryAck(result) => {
                    // Update state from discovery ack
                    // Always update zone for discoveries - if server couldn't resolve,
                    // we're in a new (unknown) zone, not the previous one
                    self.state.current_zone = result.current_zone.clone();
                    self.state.current_zone_id = result.current_zone_id.clone();
                    self.state.exits = result.exits.clone();
                    self.state.current_zone_scaling = result.scaling.clone();
                    if result.stats.total > 0 {
                        self.state.stats = Some(result.stats.clone());
                    }
                    events.push(SessionEvent::DiscoveryAcked(result));
                }
                ServerEvent::ZoneQueryAck(result) => {
                    // Update state from zone query ack
                    if result.zone.is_some() {
                        // Server resolved the zone - update state
                        self.state.current_zone = result.zone.clone();
                        self.state.current_zone_id = result.zone_id.clone();
                        self.state.exits = result.exits.clone();
                        self.state.current_zone_scaling = result.scaling.clone();
                    } else {
                        // Server couldn't resolve zone - apply same-map fallback
                        // If we're on the same map as before loading (e.g., respawn at
                        // Stake of Marika or grace in same zone), keep the current zone
                        let same_map = self.pre_loading_map_id == self.last_known_map_id;
                        if !same_map {
                            // Different map but resolution failed - clear zone
                            self.state.current_zone = None;
                            self.state.current_zone_id = None;
                            self.state.exits.clear();
                            self.state.current_zone_scaling = None;
                        }
                        // If same_map, keep the current zone (fallback)
                    }
                    // Clear pending state
                    self.pre_loading_map_id = None;
                    events.push(SessionEvent::ZoneUpdated(result));
                }
                ServerEvent::UploadLogsAck { success, message } => {
                    events.push(SessionEvent::LogsUploaded { success, message });
                }
                ServerEvent::Error(msg) => {
                    events.push(SessionEvent::ServerError(msg));
                }
                ServerEvent::StatsUpdated(stats) => {
                    // Stats-only update (on reconnection) - don't reset zone/exits
                    debug!(
                        discovered = stats.discovered,
                        total = stats.total,
                        "[SESSION] Stats updated (preserving zone/exits)"
                    );
                    self.state.stats = Some(stats.clone());
                    events.push(SessionEvent::StatsUpdated(stats));
                }
                ServerEvent::GameStatsUpdateAck => {
                    // Game stats update acknowledged - no action needed
                    debug!("[SESSION] Game stats update acknowledged");
                }
            }
        }

        events
    }
}

impl Default for TrackerSession {
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
    use crate::core::animations::Animation;
    use crate::core::io_traits::mocks::MockServerConnection;
    use crate::core::traits::mocks::{MockGameState, MockWarpDetector};
    use crate::core::types::PlayerPosition;

    fn make_pos(map_id: u32, x: f32, y: f32, z: f32) -> PlayerPosition {
        PlayerPosition::new(map_id, x, y, z, None)
    }

    /// Create a session that's already synced to the current game state.
    /// This prevents spurious zone queries on the first update.
    fn synced_session(game_state: &MockGameState, warp: &MockWarpDetector) -> TrackerSession {
        let mut session = TrackerSession::new();
        session.sync_state(game_state, warp);
        session
    }

    // -------------------------------------------------------------------------
    // Basic session tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_session_initial_state() {
        let session = TrackerSession::new();
        assert!(session.current_zone().is_none());
        assert!(session.exits().is_empty());
        assert!(session.stats().is_none());
        assert!(!session.has_pending_warp());
    }

    // -------------------------------------------------------------------------
    // Discovery flow tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_discovery_sent_on_warp_completion() {
        // Setup: fog traversal sequence
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Limgrave
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Stormveil
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );
        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890042, 0x0A0A1000);

        let mut server = MockServerConnection::new();
        // Sync state to avoid zone query on first frame with readable position
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts, pending warp created
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events.is_empty());
        assert!(session.has_pending_warp());
        game_state.advance_frame();

        // Frame 2: Animation ends, discovery sent
        let events = session.update(&game_state, &warp, &mut server);
        assert_eq!(events.len(), 1);
        assert!(
            matches!(&events[0], SessionEvent::DiscoverySent(d) if d.transport_type == "FogWall")
        );

        // Verify discovery was sent to server
        assert_eq!(server.discovery_count(), 1);
        let discovery = server.last_discovery().unwrap();
        assert_eq!(discovery.entry.map_id, 0x3C2C2400);
        assert_eq!(discovery.exit.map_id, 0x0A0A1000);
        assert_eq!(discovery.destination_entity_id, 755890042);
    }

    #[test]
    fn test_discovery_not_sent_when_disconnected() {
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)),
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)),
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );
        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890042, 0x0A0A1000);

        let mut server = MockServerConnection::disconnected();
        let mut session = TrackerSession::new();

        // Run through all frames
        for _ in 0..3 {
            session.update(&game_state, &warp, &mut server);
            game_state.advance_frame();
        }

        // No discovery should have been sent
        assert_eq!(server.discovery_count(), 0);
    }

    #[test]
    fn test_discovery_ack_updates_state() {
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Queue a discovery ack
        server.queue_discovery_ack(
            Some("Stormveil Castle".to_string()),
            vec![FogExit {
                target: "Limgrave".to_string(),
                description: "Main gate".to_string(),
                from_zone: None,
            }],
            DiscoveryStats {
                discovered: 10,
                total: 50,
            },
        );

        // Process the event
        let events = session.update(&game_state, &warp, &mut server);

        // Check event was emitted
        assert_eq!(events.len(), 1);
        assert!(matches!(&events[0], SessionEvent::DiscoveryAcked(_)));

        // Check state was updated
        assert_eq!(session.current_zone(), Some("Stormveil Castle"));
        assert_eq!(session.exits().len(), 1);
        assert_eq!(session.exits()[0].target, "Limgrave");
        assert_eq!(session.stats().unwrap().discovered, 10);
        assert_eq!(session.stats().unwrap().total, 50);
    }

    // -------------------------------------------------------------------------
    // Zone query tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_zone_query_sent_after_loading_screen() {
        // Simulate: loading screen → position readable (no warp animation)
        let game_state = MockGameState::new(
            vec![
                None,                                          // Loading
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Loaded
            ],
            vec![Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = TrackerSession::new();

        // Frame 0: Loading screen
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events.is_empty());
        game_state.advance_frame();

        // Frame 1: Position readable - zone query should be sent
        let events = session.update(&game_state, &warp, &mut server);

        // Check zone query was sent
        assert_eq!(server.zone_query_count(), 1);
        let query_pos = server.last_zone_query().unwrap();
        assert_eq!(query_pos.map_id, 0x3C2C2400);

        // Check event was emitted
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::ZoneQuerySent)));

        // Zone should be cleared while waiting
        assert!(session.current_zone().is_none());
    }

    #[test]
    fn test_zone_query_not_sent_during_warp() {
        // During a warp (with pending warp), zone query should NOT be sent
        // even when position becomes readable
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Entry
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Animation
                None,                                          // Loading
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Exit
            ],
            vec![
                Some(0),
                Some(Animation::FogWall.as_u32()),
                Some(Animation::FogWall.as_u32()),
                Some(0),
            ],
        );
        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890042, 0x0A0A1000);

        let mut server = MockServerConnection::new();
        // Sync to avoid zone query on first frame
        let mut session = synced_session(&game_state, &warp);

        // Run through remaining frames (starting from frame 1)
        for _ in 1..4 {
            game_state.advance_frame();
            session.update(&game_state, &warp, &mut server);
        }

        // Discovery should be sent, but no zone query (discovery provides zone info)
        assert_eq!(server.discovery_count(), 1);
        assert_eq!(server.zone_query_count(), 0);
    }

    #[test]
    fn test_zone_query_ack_updates_state() {
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Queue a zone query ack
        server.queue_zone_ack(
            Some("Limgrave".to_string()),
            vec![
                FogExit {
                    target: "???".to_string(),
                    description: "North".to_string(),
                    from_zone: None,
                },
                FogExit {
                    target: "Stormveil Castle".to_string(),
                    description: "East".to_string(),
                    from_zone: None,
                },
            ],
        );

        // Process the event
        let events = session.update(&game_state, &warp, &mut server);

        // Check event was emitted
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::ZoneUpdated(_))));

        // Check state was updated
        assert_eq!(session.current_zone(), Some("Limgrave"));
        assert_eq!(session.exits().len(), 2);
    }

    // -------------------------------------------------------------------------
    // Multiple events tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_multiple_server_events_processed() {
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Queue multiple events
        server.queue_event(ServerEvent::StatusChanged(ConnectionStatus::Reconnecting));
        server.queue_event(ServerEvent::StatusChanged(ConnectionStatus::Connected));
        server.queue_event(ServerEvent::Error("test warning".to_string()));

        // Process all events in one update
        let events = session.update(&game_state, &warp, &mut server);

        assert_eq!(events.len(), 3);
        assert!(matches!(
            &events[0],
            SessionEvent::ConnectionChanged(ConnectionStatus::Reconnecting)
        ));
        assert!(matches!(
            &events[1],
            SessionEvent::ConnectionChanged(ConnectionStatus::Connected)
        ));
        assert!(matches!(&events[2], SessionEvent::ServerError(msg) if msg == "test warning"));
    }

    // -------------------------------------------------------------------------
    // Full integration flow tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_complete_discovery_flow() {
        // Full flow: warp → discovery sent → ack received → state updated
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Limgrave
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Animation
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Stormveil
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Idle
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        warp.set_warp(true, 755890042, 0x0A0A1000);

        let mut server = MockServerConnection::new();
        let mut session = TrackerSession::new();

        // Frame 0: Idle
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 1: Animation starts
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Discovery sent
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::DiscoverySent(_))));
        game_state.advance_frame();

        // Server responds with ack
        server.queue_discovery_ack(
            Some("Stormveil Castle".to_string()),
            vec![FogExit {
                target: "Limgrave".to_string(),
                description: "Back".to_string(),
                from_zone: None,
            }],
            DiscoveryStats {
                discovered: 1,
                total: 50,
            },
        );

        // Frame 3: Ack processed
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::DiscoveryAcked(_))));

        // Verify final state
        assert_eq!(session.current_zone(), Some("Stormveil Castle"));
        assert_eq!(session.exits().len(), 1);
        assert_eq!(session.stats().unwrap().discovered, 1);
    }

    #[test]
    fn test_multiple_warps_in_succession() {
        // Test: warp A→B, then immediately B→C
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // A
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Anim 1
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // B
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Anim 2
                Some(make_pos(0x3C3A3800, 300.0, 0.0, 300.0)), // C
            ],
            vec![
                Some(0),
                Some(Animation::FogWall.as_u32()),
                Some(0),
                Some(Animation::FogWall.as_u32()),
                Some(0),
            ],
        );

        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = TrackerSession::new();

        // Frame 0: Idle at A
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 1: First warp starts
        warp.set_warp(true, 755890001, 0x0A0A1000);
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: First warp completes
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::DiscoverySent(_))));
        game_state.advance_frame();

        // Frame 3: Second warp starts
        warp.set_warp(true, 755890002, 0x3C3A3800);
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 4: Second warp completes
        let events = session.update(&game_state, &warp, &mut server);
        assert!(events
            .iter()
            .any(|e| matches!(e, SessionEvent::DiscoverySent(_))));

        // Both discoveries should have been sent
        assert_eq!(server.discovery_count(), 2);
    }

    // -------------------------------------------------------------------------
    // Error handling tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_server_error_event() {
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        server.queue_event(ServerEvent::Error("Game not found".to_string()));

        let events = session.update(&game_state, &warp, &mut server);

        assert_eq!(events.len(), 1);
        match &events[0] {
            SessionEvent::ServerError(msg) => assert_eq!(msg, "Game not found"),
            _ => panic!("Expected ServerError event"),
        }
    }

    #[test]
    fn test_discovery_ack_with_null_zone() {
        // Server may return null zone if resolution failed
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Set initial state
        session.state.current_zone = Some("Limgrave".to_string());
        session.state.current_zone_id = Some("limgrave".to_string());

        // Queue ack with null zone (resolution failed)
        server.queue_event(ServerEvent::DiscoveryAck(DiscoveryResult {
            propagated: Vec::new(),
            current_zone: None,
            current_zone_id: None,
            exits: Vec::new(),
            stats: DiscoveryStats {
                discovered: 5,
                total: 50,
            },
            scaling: None,
        }));

        session.update(&game_state, &warp, &mut server);

        // Zone SHOULD be cleared for discoveries - if we traversed a fog gate
        // and server couldn't resolve, we're in a new unknown zone, not the old one
        assert_eq!(session.current_zone(), None);
        assert_eq!(session.current_zone_id(), None);
        // Stats should still update
        assert_eq!(session.stats().unwrap().discovered, 5);
    }

    // -------------------------------------------------------------------------
    // Grace entity ID tests (fast travel zone resolution)
    // -------------------------------------------------------------------------

    #[test]
    fn test_zone_query_includes_target_grace_entity_id() {
        // When fast traveling, target_grace is captured when warp starts
        // and included in the zone_query after loading completes
        const GRACE_ENTITY_ID: u32 = 1042362951; // "The First Step" grace

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Starting position (sync)
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Warp starts
                None,                                          // Loading screen
                Some(make_pos(0x3C2C2400, 200.0, 0.0, 200.0)), // Destination (Limgrave)
            ],
            vec![Some(0), Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Fast travel warp starts - target_grace is captured here
        // (non-fog-rando entity ID = spawn point at grace)
        warp.set_warp(true, 14000981, 0x3C2C2400); // Spawn point entity
        warp.set_target_grace(GRACE_ENTITY_ID);
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Loading screen - warp_requested goes false
        warp.set_warp(false, 0, 0);
        warp.set_target_grace(0); // TargetGrace is cleared after warp
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 3: Position readable - zone query uses captured target_grace
        session.update(&game_state, &warp, &mut server);

        // Verify zone query was sent with the target grace entity ID
        assert_eq!(server.zone_query_count(), 1);
        assert_eq!(
            server.last_zone_query_grace_entity_id(),
            Some(GRACE_ENTITY_ID)
        );
    }

    #[test]
    fn test_zone_query_target_grace_captured_early() {
        // TargetGrace is only available while warp_requested is true
        // We must capture it immediately when the warp starts
        const GRACE_ENTITY_ID: u32 = 1042362951;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Starting (sync)
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Warp frame
                Some(make_pos(0x0A0A1000, 100.0, 0.0, 100.0)), // Warp ongoing
                None,                                          // Loading screen
                Some(make_pos(0x3C2C2400, 50.0, 0.0, 50.0)),   // Destination
            ],
            vec![Some(0), Some(0), Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Warp starts - target_grace is available
        warp.set_warp(true, 14000981, 0x3C2C2400);
        warp.set_target_grace(GRACE_ENTITY_ID);
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Warp still in progress, but target_grace might clear early
        warp.set_target_grace(0); // Some implementations clear this early
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 3: Warp ends, loading starts
        warp.set_warp(false, 0, 0);
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 4: Loading done - zone query should use captured value
        session.update(&game_state, &warp, &mut server);

        // Verify we captured target_grace from frame 1
        assert_eq!(server.zone_query_count(), 1);
        assert_eq!(
            server.last_zone_query_grace_entity_id(),
            Some(GRACE_ENTITY_ID)
        );
    }

    #[test]
    fn test_zone_query_no_grace_entity_id_for_death() {
        // When player dies (no warp requested), zone query should not have grace entity ID
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Playing (sync frame)
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Still playing
                None,                                          // Death loading
                Some(make_pos(0x3C2C2400, 50.0, 0.0, 50.0)),   // Respawn at grace
            ],
            vec![Some(0), Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new(); // No warp requested (death)
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Playing normally
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Death loading screen
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 3: Respawn - zone query without grace entity ID
        session.update(&game_state, &warp, &mut server);

        // Verify zone query was sent without grace entity ID
        assert_eq!(server.zone_query_count(), 1);
        assert_eq!(server.last_zone_query_grace_entity_id(), None);
    }

    #[test]
    fn test_fog_gate_discovery_does_not_capture_grace_entity_id() {
        // For fog gate traversals, the destination_entity_id is a fog rando entity (755890xxx)
        // Zone info comes from discovery ack, not zone query
        const FOG_RANDO_ENTITY: u32 = 755890042;

        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Entry zone
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Animation starts
                Some(make_pos(0x0A0A1000, 200.0, 0.0, 200.0)), // Exit zone
            ],
            vec![Some(0), Some(Animation::FogWall.as_u32()), Some(0)],
        );
        let warp = MockWarpDetector::new();
        warp.set_warp(true, FOG_RANDO_ENTITY, 0x0A0A1000);

        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Animation starts, pending warp created
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Animation ends, discovery sent
        session.update(&game_state, &warp, &mut server);

        // Discovery should be sent (not zone query)
        assert_eq!(server.discovery_count(), 1);
        assert_eq!(server.zone_query_count(), 0);
    }

    // -------------------------------------------------------------------------
    // Same-map fallback tests (respawn at Stake of Marika or same-zone grace)
    // -------------------------------------------------------------------------

    #[test]
    fn test_zone_query_same_map_fallback_keeps_zone() {
        // When server returns zone: None but we're on the same map
        // (e.g., respawn at Stake of Marika), keep the current zone
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Playing (sync)
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Still playing
                None,                                          // Death loading
                Some(make_pos(0x3C2C2400, 50.0, 0.0, 50.0)),   // Respawn (same map!)
            ],
            vec![Some(0), Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Set initial zone state (simulating we were in Limgrave)
        session.state.current_zone = Some("Limgrave".to_string());
        session.state.exits = vec![FogExit {
            target: "???".to_string(),
            description: "North".to_string(),
            from_zone: None,
        }];
        game_state.advance_frame();

        // Frame 1: Playing normally
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Death loading screen
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 3: Respawn - zone query sent
        session.update(&game_state, &warp, &mut server);
        assert_eq!(server.zone_query_count(), 1);

        // Server responds with zone: None (couldn't resolve)
        server.queue_zone_ack(None, Vec::new());

        // Process the ack
        session.update(&game_state, &warp, &mut server);

        // Zone should be kept (same-map fallback)
        assert_eq!(session.current_zone(), Some("Limgrave"));
        // Exits should also be kept
        assert_eq!(session.exits().len(), 1);
    }

    #[test]
    fn test_zone_query_different_map_clears_zone() {
        // When server returns zone: None and we're on a different map,
        // the zone should be cleared (we don't know where we are)
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Playing in map A (sync)
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Still playing
                None,                                          // Loading
                Some(make_pos(0x0A0A1000, 50.0, 0.0, 50.0)),   // Arrived in map B (different!)
            ],
            vec![Some(0), Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Set initial zone state
        session.state.current_zone = Some("Limgrave".to_string());
        session.state.exits = vec![FogExit {
            target: "???".to_string(),
            description: "North".to_string(),
            from_zone: None,
        }];
        game_state.advance_frame();

        // Frame 1: Playing normally
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Loading screen
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 3: Arrived at different map - zone query sent
        session.update(&game_state, &warp, &mut server);
        assert_eq!(server.zone_query_count(), 1);

        // Server responds with zone: None (couldn't resolve)
        server.queue_zone_ack(None, Vec::new());

        // Process the ack
        session.update(&game_state, &warp, &mut server);

        // Zone should be cleared (different map, no fallback)
        assert!(session.current_zone().is_none());
        assert!(session.exits().is_empty());
    }

    #[test]
    fn test_zone_query_success_clears_pre_loading_state() {
        // When server successfully resolves zone, pre_loading_map_id should be cleared
        let game_state = MockGameState::new(
            vec![
                Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0)), // Playing (sync)
                None,                                          // Loading
                Some(make_pos(0x3C2C2400, 50.0, 0.0, 50.0)),   // Respawn
            ],
            vec![Some(0), Some(0), Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);
        game_state.advance_frame();

        // Frame 1: Loading screen
        session.update(&game_state, &warp, &mut server);
        game_state.advance_frame();

        // Frame 2: Zone query sent
        session.update(&game_state, &warp, &mut server);
        assert_eq!(server.zone_query_count(), 1);

        // Server responds with a zone
        server.queue_zone_ack(
            Some("Limgrave".to_string()),
            vec![FogExit {
                target: "Stormveil".to_string(),
                description: "Castle".to_string(),
                from_zone: None,
            }],
        );

        // Process the ack
        session.update(&game_state, &warp, &mut server);

        // Zone should be updated to server response
        assert_eq!(session.current_zone(), Some("Limgrave"));
        assert_eq!(session.exits().len(), 1);
        assert_eq!(session.exits()[0].target, "Stormveil");
    }

    // -------------------------------------------------------------------------
    // Stats update tests (reconnection preserves zone/exits)
    // -------------------------------------------------------------------------

    #[test]
    fn test_stats_updated_preserves_zone_and_exits() {
        // When the server sends StatsUpdated (on reconnection), zone and exits
        // should be preserved, only stats should be updated
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // Set initial state (simulating we were in Limgrave before disconnect)
        session.state.current_zone = Some("Limgrave".to_string());
        session.state.current_zone_id = Some("limgrave".to_string());
        session.state.exits = vec![
            FogExit {
                target: "Stormveil Castle".to_string(),
                description: "North".to_string(),
                from_zone: None,
            },
            FogExit {
                target: "???".to_string(),
                description: "East".to_string(),
                from_zone: None,
            },
        ];
        session.state.stats = Some(DiscoveryStats {
            discovered: 5,
            total: 50,
        });
        session.state.current_zone_scaling = Some("Scaling: tier 1".to_string());

        // Simulate reconnection: server sends StatsUpdated (only stats, no zone)
        server.queue_event(ServerEvent::StatsUpdated(DiscoveryStats {
            discovered: 10,
            total: 55,
        }));

        // Process the event
        let events = session.update(&game_state, &warp, &mut server);

        // Check event was emitted
        assert_eq!(events.len(), 1);
        assert!(matches!(&events[0], SessionEvent::StatsUpdated(stats) if stats.discovered == 10));

        // Zone and exits should be PRESERVED (not reset)
        assert_eq!(session.current_zone(), Some("Limgrave"));
        assert_eq!(session.current_zone_id(), Some("limgrave"));
        assert_eq!(session.exits().len(), 2);
        assert_eq!(session.exits()[0].target, "Stormveil Castle");
        assert_eq!(session.current_zone_scaling(), Some("Scaling: tier 1"));

        // Only stats should be updated
        assert_eq!(session.stats().unwrap().discovered, 10);
        assert_eq!(session.stats().unwrap().total, 55);
    }

    #[test]
    fn test_stats_updated_works_with_no_prior_state() {
        // StatsUpdated should work even if there's no prior zone state
        let game_state = MockGameState::new(
            vec![Some(make_pos(0x3C2C2400, 100.0, 0.0, 100.0))],
            vec![Some(0)],
        );
        let warp = MockWarpDetector::new();
        let mut server = MockServerConnection::new();
        let mut session = synced_session(&game_state, &warp);

        // No initial state (fresh session)
        assert!(session.current_zone().is_none());
        assert!(session.stats().is_none());

        // Simulate reconnection: server sends StatsUpdated
        server.queue_event(ServerEvent::StatsUpdated(DiscoveryStats {
            discovered: 10,
            total: 55,
        }));

        // Process the event
        let events = session.update(&game_state, &warp, &mut server);

        // Check event was emitted
        assert_eq!(events.len(), 1);

        // Zone should still be None (no zone info was provided)
        assert!(session.current_zone().is_none());

        // Stats should be updated
        assert_eq!(session.stats().unwrap().discovered, 10);
        assert_eq!(session.stats().unwrap().total, 55);
    }
}
