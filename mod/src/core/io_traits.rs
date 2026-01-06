//! I/O traits for tracker session operations
//!
//! These traits abstract network and timing operations, enabling
//! integration tests on Linux with mock implementations.

use crate::core::protocol::{DiscoveryStats, FogExit, PropagatedLink};
use crate::core::types::PlayerPosition;
use crate::core::warp_tracker::DiscoveryEvent;

// =============================================================================
// GAME STATS
// =============================================================================

/// Game statistics for tracking progression
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct GameStats {
    /// List of great rune names collected (e.g., ["Godrick", "Radahn"])
    pub great_runes: Vec<String>,
    /// Number of kindling items collected
    pub kindling_count: u32,
    /// Number of deaths
    pub death_count: u32,
    /// In-game time in milliseconds
    pub play_time_ms: u32,
}

impl GameStats {
    /// Create a new GameStats instance
    pub fn new(
        great_runes: Vec<String>,
        kindling_count: u32,
        death_count: u32,
        play_time_ms: u32,
    ) -> Self {
        Self {
            great_runes,
            kindling_count,
            death_count,
            play_time_ms,
        }
    }

    /// Check if stats have meaningfully changed (ignoring play_time_ms changes alone)
    ///
    /// Returns true if great_runes, kindling_count, or death_count differ.
    /// play_time_ms alone changing does not trigger an update (it changes every frame).
    /// For great_runes, comparison is order-independent (sorted before comparing).
    pub fn has_meaningful_change(&self, other: &GameStats) -> bool {
        // Compare runes in sorted order (game may return them in variable order)
        let mut self_runes = self.great_runes.clone();
        let mut other_runes = other.great_runes.clone();
        self_runes.sort();
        other_runes.sort();

        self_runes != other_runes
            || self.kindling_count != other.kindling_count
            || self.death_count != other.death_count
    }

    /// Check if stats represent an empty/inactive game state
    ///
    /// Returns true if all values are at their initial state (no runes, no kindling,
    /// no deaths, no play time). This happens when the player is not in an active game.
    pub fn is_empty(&self) -> bool {
        self.great_runes.is_empty()
            && self.kindling_count == 0
            && self.death_count == 0
            && self.play_time_ms == 0
    }
}

// =============================================================================
// CONNECTION STATUS
// =============================================================================

/// Connection status for server communication
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionStatus {
    /// Not connected to server
    Disconnected,
    /// Attempting to connect
    Connecting,
    /// Connected and authenticated
    Connected,
    /// Connection lost, attempting to reconnect
    Reconnecting,
    /// Connection error occurred
    Error,
}

// =============================================================================
// SERVER RESPONSE TYPES
// =============================================================================

/// Result of sending a discovery to the server
#[derive(Debug, Clone, PartialEq)]
pub struct DiscoveryResult {
    /// Links that were propagated as a result of this discovery
    pub propagated: Vec<PropagatedLink>,
    /// Current zone name (after the warp)
    pub current_zone: Option<String>,
    /// Zone key (e.g., "limgrave_stormhill")
    pub current_zone_id: Option<String>,
    /// Available exits from current zone
    pub exits: Vec<FogExit>,
    /// Updated discovery statistics
    pub stats: DiscoveryStats,
    /// Zone scaling text (e.g., "Scaling: tier 1, previously 2")
    pub scaling: Option<String>,
}

/// Result of a zone query
#[derive(Debug, Clone, PartialEq)]
pub struct ZoneQueryResult {
    /// Current zone name
    pub zone: Option<String>,
    /// Zone key (e.g., "limgrave_stormhill")
    pub zone_id: Option<String>,
    /// Available exits from current zone
    pub exits: Vec<FogExit>,
    /// Zone scaling text (e.g., "Scaling: tier 1, previously 2")
    pub scaling: Option<String>,
}

/// Events received from the server
#[derive(Debug, Clone, PartialEq)]
pub enum ServerEvent {
    /// Connection status changed
    StatusChanged(ConnectionStatus),
    /// Server acknowledged a discovery
    DiscoveryAck(DiscoveryResult),
    /// Server responded to a zone query
    ZoneQueryAck(ZoneQueryResult),
    /// Server acknowledged log upload
    UploadLogsAck {
        success: bool,
        message: Option<String>,
    },
    /// Server sent an error message
    Error(String),
    /// Stats-only update (used on reconnection, doesn't reset zone/exits)
    StatsUpdated(DiscoveryStats),
    /// Server acknowledged game stats update
    GameStatsUpdateAck,
}

// =============================================================================
// I/O TRAITS
// =============================================================================

/// Trait for sending discoveries and queries to the server
pub trait DiscoverySender {
    /// Check if the sender is connected
    fn is_connected(&self) -> bool;

    /// Get current connection status
    fn status(&self) -> ConnectionStatus;

    /// Send a fog gate discovery to the server
    ///
    /// The `source_zone` and `source_zone_id` parameters are the mod's cached zone info,
    /// used by the server for disambiguation. Pass `None` if not available.
    fn send_discovery(
        &self,
        event: &DiscoveryEvent,
        source_zone: Option<&str>,
        source_zone_id: Option<&str>,
    );

    /// Send a zone query (after loading screen exit)
    ///
    /// The `grace_entity_id` parameter is the entity ID of the grace being fast traveled to.
    /// Pass `None` for non-fast-travel zone queries (fog gate traversals, deaths, etc.)
    fn send_zone_query(&self, position: &PlayerPosition, grace_entity_id: Option<u32>);

    /// Send game stats update to the server
    fn send_game_stats_update(&self, stats: &GameStats);
}

/// Trait for receiving events from the server
pub trait ServerEventReceiver {
    /// Poll for the next server event (non-blocking)
    ///
    /// Returns `Some(event)` if an event is available, `None` otherwise.
    fn poll_event(&mut self) -> Option<ServerEvent>;
}

/// Combined trait for full server communication
///
/// This is automatically implemented for any type that implements
/// both `DiscoverySender` and `ServerEventReceiver`.
pub trait ServerConnection: DiscoverySender + ServerEventReceiver {}
impl<T: DiscoverySender + ServerEventReceiver> ServerConnection for T {}

// =============================================================================
// MOCK IMPLEMENTATIONS FOR TESTING
// =============================================================================

#[cfg(test)]
pub mod mocks {
    use super::*;
    use std::cell::RefCell;

    /// A zone query with position and optional grace entity ID
    #[derive(Debug, Clone)]
    pub struct ZoneQueryRecord {
        pub position: PlayerPosition,
        pub grace_entity_id: Option<u32>,
    }

    /// Mock server connection for testing
    ///
    /// This mock allows tests to:
    /// - Track what discoveries and zone queries were sent
    /// - Queue server events to be returned by `poll_event()`
    /// - Control connection status
    pub struct MockServerConnection {
        /// Whether the mock is "connected"
        pub connected: RefCell<bool>,
        /// Discoveries that were sent
        pub discoveries_sent: RefCell<Vec<DiscoveryEvent>>,
        /// Zone queries that were sent (with grace entity ID)
        pub zone_queries_sent: RefCell<Vec<ZoneQueryRecord>>,
        /// Game stats updates that were sent
        pub game_stats_sent: RefCell<Vec<GameStats>>,
        /// Events to return from poll_event()
        pub pending_events: RefCell<Vec<ServerEvent>>,
    }

    impl MockServerConnection {
        /// Create a new connected mock server
        pub fn new() -> Self {
            Self {
                connected: RefCell::new(true),
                discoveries_sent: RefCell::new(Vec::new()),
                zone_queries_sent: RefCell::new(Vec::new()),
                game_stats_sent: RefCell::new(Vec::new()),
                pending_events: RefCell::new(Vec::new()),
            }
        }

        /// Create a disconnected mock server
        pub fn disconnected() -> Self {
            let mock = Self::new();
            *mock.connected.borrow_mut() = false;
            mock
        }

        /// Set connection status
        pub fn set_connected(&self, connected: bool) {
            *self.connected.borrow_mut() = connected;
        }

        /// Queue a server event to be returned by poll_event()
        pub fn queue_event(&self, event: ServerEvent) {
            self.pending_events.borrow_mut().push(event);
        }

        /// Queue a discovery acknowledgment
        pub fn queue_discovery_ack(
            &self,
            zone: Option<String>,
            exits: Vec<FogExit>,
            stats: DiscoveryStats,
        ) {
            self.queue_event(ServerEvent::DiscoveryAck(DiscoveryResult {
                propagated: Vec::new(),
                current_zone: zone,
                current_zone_id: None,
                exits,
                stats,
                scaling: None,
            }));
        }

        /// Queue a zone query acknowledgment
        pub fn queue_zone_ack(&self, zone: Option<String>, exits: Vec<FogExit>) {
            self.queue_event(ServerEvent::ZoneQueryAck(ZoneQueryResult {
                zone,
                zone_id: None,
                exits,
                scaling: None,
            }));
        }

        /// Get the number of discoveries sent
        pub fn discovery_count(&self) -> usize {
            self.discoveries_sent.borrow().len()
        }

        /// Get the number of zone queries sent
        pub fn zone_query_count(&self) -> usize {
            self.zone_queries_sent.borrow().len()
        }

        /// Get the last discovery sent, if any
        pub fn last_discovery(&self) -> Option<DiscoveryEvent> {
            self.discoveries_sent.borrow().last().cloned()
        }

        /// Get the last zone query sent, if any (position only, for backward compatibility)
        pub fn last_zone_query(&self) -> Option<PlayerPosition> {
            self.zone_queries_sent
                .borrow()
                .last()
                .map(|r| r.position.clone())
        }

        /// Get the last zone query record (with grace entity ID)
        pub fn last_zone_query_record(&self) -> Option<ZoneQueryRecord> {
            self.zone_queries_sent.borrow().last().cloned()
        }

        /// Get the last grace entity ID sent with a zone query
        pub fn last_zone_query_grace_entity_id(&self) -> Option<u32> {
            self.zone_queries_sent
                .borrow()
                .last()
                .and_then(|r| r.grace_entity_id)
        }
    }

    impl Default for MockServerConnection {
        fn default() -> Self {
            Self::new()
        }
    }

    impl DiscoverySender for MockServerConnection {
        fn is_connected(&self) -> bool {
            *self.connected.borrow()
        }

        fn status(&self) -> ConnectionStatus {
            if *self.connected.borrow() {
                ConnectionStatus::Connected
            } else {
                ConnectionStatus::Disconnected
            }
        }

        fn send_discovery(
            &self,
            event: &DiscoveryEvent,
            _source_zone: Option<&str>,
            _source_zone_id: Option<&str>,
        ) {
            self.discoveries_sent.borrow_mut().push(event.clone());
        }

        fn send_zone_query(&self, position: &PlayerPosition, grace_entity_id: Option<u32>) {
            self.zone_queries_sent.borrow_mut().push(ZoneQueryRecord {
                position: position.clone(),
                grace_entity_id,
            });
        }

        fn send_game_stats_update(&self, stats: &GameStats) {
            self.game_stats_sent.borrow_mut().push(stats.clone());
        }
    }

    impl ServerEventReceiver for MockServerConnection {
        fn poll_event(&mut self) -> Option<ServerEvent> {
            let mut events = self.pending_events.borrow_mut();
            if events.is_empty() {
                None
            } else {
                Some(events.remove(0))
            }
        }
    }
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::mocks::*;
    use super::*;
    use crate::core::types::PlayerPosition;
    use crate::core::warp_tracker::DiscoveryEvent;

    fn make_pos(map_id: u32, x: f32, y: f32, z: f32) -> PlayerPosition {
        PlayerPosition::new(map_id, x, y, z, None)
    }

    fn make_discovery() -> DiscoveryEvent {
        DiscoveryEvent {
            entry: make_pos(0x3C2C2400, 100.0, 0.0, 100.0),
            exit: make_pos(0x0A0A1000, 200.0, 0.0, 200.0),
            transport_type: "FogWall".to_string(),
            destination_entity_id: 755890042,
            warp_was_requested: false,
        }
    }

    #[test]
    fn test_mock_server_connected_by_default() {
        let server = MockServerConnection::new();
        assert!(server.is_connected());
        assert_eq!(server.status(), ConnectionStatus::Connected);
    }

    #[test]
    fn test_mock_server_disconnected() {
        let server = MockServerConnection::disconnected();
        assert!(!server.is_connected());
        assert_eq!(server.status(), ConnectionStatus::Disconnected);
    }

    #[test]
    fn test_mock_server_tracks_discoveries() {
        let server = MockServerConnection::new();
        let discovery = make_discovery();

        assert_eq!(server.discovery_count(), 0);
        server.send_discovery(&discovery, Some("Limgrave"), Some("limgrave"));
        assert_eq!(server.discovery_count(), 1);

        let last = server.last_discovery().unwrap();
        assert_eq!(last.entry.map_id, 0x3C2C2400);
        assert_eq!(last.exit.map_id, 0x0A0A1000);
    }

    #[test]
    fn test_mock_server_tracks_zone_queries() {
        let server = MockServerConnection::new();
        let pos = make_pos(0x3C2C2400, 100.0, 50.0, 100.0);

        assert_eq!(server.zone_query_count(), 0);
        server.send_zone_query(&pos, None);
        assert_eq!(server.zone_query_count(), 1);

        let last = server.last_zone_query().unwrap();
        assert_eq!(last.map_id, 0x3C2C2400);
    }

    #[test]
    fn test_mock_server_queued_events() {
        let mut server = MockServerConnection::new();

        // Queue some events
        server.queue_discovery_ack(
            Some("Stormveil Castle".to_string()),
            Vec::new(),
            DiscoveryStats {
                discovered: 5,
                total: 50,
            },
        );
        server.queue_zone_ack(Some("Limgrave".to_string()), Vec::new());
        server.queue_event(ServerEvent::Error("test error".to_string()));

        // Poll them in order
        let event1 = server.poll_event().unwrap();
        assert!(matches!(event1, ServerEvent::DiscoveryAck(_)));

        let event2 = server.poll_event().unwrap();
        assert!(matches!(event2, ServerEvent::ZoneQueryAck(_)));

        let event3 = server.poll_event().unwrap();
        assert!(matches!(event3, ServerEvent::Error(_)));

        // No more events
        assert!(server.poll_event().is_none());
    }

    #[test]
    fn test_connection_status_variants() {
        assert_ne!(ConnectionStatus::Connected, ConnectionStatus::Disconnected);
        assert_ne!(ConnectionStatus::Connecting, ConnectionStatus::Reconnecting);
        assert_ne!(ConnectionStatus::Error, ConnectionStatus::Connected);
    }

    // -------------------------------------------------------------------------
    // GameStats tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_game_stats_default() {
        let stats = GameStats::default();
        assert!(stats.great_runes.is_empty());
        assert_eq!(stats.kindling_count, 0);
        assert_eq!(stats.death_count, 0);
        assert_eq!(stats.play_time_ms, 0);
    }

    #[test]
    fn test_game_stats_new() {
        let stats = GameStats::new(
            vec!["Godrick".to_string(), "Radahn".to_string()],
            5,
            42,
            3600000,
        );
        assert_eq!(stats.great_runes, vec!["Godrick", "Radahn"]);
        assert_eq!(stats.kindling_count, 5);
        assert_eq!(stats.death_count, 42);
        assert_eq!(stats.play_time_ms, 3600000);
    }

    #[test]
    fn test_game_stats_meaningful_change_death_count() {
        let stats1 = GameStats::new(vec!["Godrick".to_string()], 0, 5, 1000);
        let stats2 = GameStats::new(vec!["Godrick".to_string()], 0, 6, 1000);
        assert!(stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_meaningful_change_kindling() {
        let stats1 = GameStats::new(vec!["Godrick".to_string()], 0, 5, 1000);
        let stats2 = GameStats::new(vec!["Godrick".to_string()], 1, 5, 1000);
        assert!(stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_meaningful_change_runes() {
        let stats1 = GameStats::new(vec!["Godrick".to_string()], 0, 5, 1000);
        let stats2 = GameStats::new(
            vec!["Godrick".to_string(), "Radahn".to_string()],
            0,
            5,
            1000,
        );
        assert!(stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_no_meaningful_change_play_time_only() {
        let stats1 = GameStats::new(vec!["Godrick".to_string()], 5, 10, 1000);
        let stats2 = GameStats::new(vec!["Godrick".to_string()], 5, 10, 2000);
        // play_time_ms changed, but no meaningful change
        assert!(!stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_no_change() {
        let stats1 = GameStats::new(vec!["Godrick".to_string()], 5, 10, 1000);
        let stats2 = GameStats::new(vec!["Godrick".to_string()], 5, 10, 1000);
        assert!(!stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_no_meaningful_change_rune_order() {
        // Same runes but in different order should NOT be considered a change
        let stats1 = GameStats::new(
            vec![
                "Godrick".to_string(),
                "Morgott".to_string(),
                "Malenia".to_string(),
                "Mohg".to_string(),
            ],
            6,
            74,
            57891968,
        );
        let stats2 = GameStats::new(
            vec![
                "Malenia".to_string(),
                "Morgott".to_string(),
                "Mohg".to_string(),
                "Godrick".to_string(),
            ],
            6,
            74,
            57891968,
        );
        assert!(!stats1.has_meaningful_change(&stats2));
    }

    #[test]
    fn test_game_stats_is_empty() {
        let empty = GameStats::default();
        assert!(empty.is_empty());

        let with_runes = GameStats::new(vec!["Godrick".to_string()], 0, 0, 0);
        assert!(!with_runes.is_empty());

        let with_kindling = GameStats::new(vec![], 1, 0, 0);
        assert!(!with_kindling.is_empty());

        let with_deaths = GameStats::new(vec![], 0, 1, 0);
        assert!(!with_deaths.is_empty());

        let with_time = GameStats::new(vec![], 0, 0, 1000);
        assert!(!with_time.is_empty());
    }

    #[test]
    fn test_mock_server_tracks_game_stats() {
        let server = MockServerConnection::new();
        let stats = GameStats::new(vec!["Godrick".to_string()], 5, 42, 3600000);

        assert!(server.game_stats_sent.borrow().is_empty());
        server.send_game_stats_update(&stats);
        assert_eq!(server.game_stats_sent.borrow().len(), 1);
        assert_eq!(server.game_stats_sent.borrow()[0], stats);
    }
}
