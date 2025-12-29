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
    /// Server error occurred
    ServerError(String),
}

// =============================================================================
// SESSION STATE
// =============================================================================

/// Session state updated from server responses
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SessionState {
    /// Current zone name
    pub current_zone: Option<String>,
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
}

impl TrackerSession {
    /// Create a new tracker session
    pub fn new() -> Self {
        Self {
            warp_tracker: WarpTracker::new(),
            state: SessionState::default(),
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

        // 1. Check for loading screen exit BEFORE check_warp (which updates state)
        // This must be done first because check_warp updates was_position_readable
        let just_exited_loading = self.warp_tracker.just_exited_loading_screen(game_state);

        // 2. Check for warp completion
        if let Some(discovery) = self.warp_tracker.check_warp(game_state, warp_detector) {
            if server.is_connected() {
                server.send_discovery(&discovery);
                events.push(SessionEvent::DiscoverySent(discovery));
            }
        }

        // 3. Send zone query if we just exited a loading screen (without a pending warp)
        if just_exited_loading {
            if server.is_connected() {
                if let Some(pos) = game_state.read_position() {
                    server.send_zone_query(&pos);
                    // Clear zone while waiting for response
                    self.state.current_zone = None;
                    self.state.exits.clear();
                    self.state.current_zone_scaling = None;
                    events.push(SessionEvent::ZoneQuerySent);
                }
            }
        }

        // 4. Poll and process server events
        while let Some(event) = server.poll_event() {
            match event {
                ServerEvent::StatusChanged(status) => {
                    events.push(SessionEvent::ConnectionChanged(status));
                }
                ServerEvent::DiscoveryAck(result) => {
                    // Update state from discovery ack
                    if result.current_zone.is_some() {
                        self.state.current_zone = result.current_zone.clone();
                        self.state.exits = result.exits.clone();
                        self.state.current_zone_scaling = result.scaling.clone();
                    }
                    if result.stats.total > 0 {
                        self.state.stats = Some(result.stats.clone());
                    }
                    events.push(SessionEvent::DiscoveryAcked(result));
                }
                ServerEvent::ZoneQueryAck(result) => {
                    // Update state from zone query ack
                    if result.zone.is_some() {
                        self.state.current_zone = result.zone.clone();
                        self.state.exits = result.exits.clone();
                        self.state.current_zone_scaling = result.scaling.clone();
                    }
                    events.push(SessionEvent::ZoneUpdated(result));
                }
                ServerEvent::Error(msg) => {
                    events.push(SessionEvent::ServerError(msg));
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

        // Queue ack with null zone (resolution failed)
        server.queue_event(ServerEvent::DiscoveryAck(DiscoveryResult {
            propagated: Vec::new(),
            current_zone: None,
            exits: Vec::new(),
            stats: DiscoveryStats {
                discovered: 5,
                total: 50,
            },
            scaling: None,
        }));

        session.update(&game_state, &warp, &mut server);

        // Zone should NOT be cleared (only update if Some)
        assert_eq!(session.current_zone(), Some("Limgrave"));
        // Stats should still update
        assert_eq!(session.stats().unwrap().discovered, 5);
    }
}
