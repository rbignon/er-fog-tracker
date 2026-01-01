//! I/O traits for tracker session operations
//!
//! These traits abstract network and timing operations, enabling
//! integration tests on Linux with mock implementations.

use crate::core::protocol::{DiscoveryStats, FogExit, PropagatedLink};
use crate::core::types::PlayerPosition;
use crate::core::warp_tracker::DiscoveryEvent;

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
    /// Current zone internal key (e.g., "limgrave_stormhill")
    pub current_zone_key: Option<String>,
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
    /// Zone internal key (e.g., "limgrave_stormhill")
    pub zone_key: Option<String>,
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
    /// Server sent an error message
    Error(String),
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
    /// The `source_zone` and `source_zone_key` parameters are the mod's cached zone info,
    /// used by the server for disambiguation. Pass `None` if not available.
    fn send_discovery(
        &self,
        event: &DiscoveryEvent,
        source_zone: Option<&str>,
        source_zone_key: Option<&str>,
    );

    /// Send a zone query (after loading screen exit)
    ///
    /// The `grace_entity_id` parameter is the entity ID of the grace being fast traveled to.
    /// Pass `None` for non-fast-travel zone queries (fog gate traversals, deaths, etc.)
    fn send_zone_query(&self, position: &PlayerPosition, grace_entity_id: Option<u32>);
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
                current_zone_key: None,
                exits,
                stats,
                scaling: None,
            }));
        }

        /// Queue a zone query acknowledgment
        pub fn queue_zone_ack(&self, zone: Option<String>, exits: Vec<FogExit>) {
            self.queue_event(ServerEvent::ZoneQueryAck(ZoneQueryResult {
                zone,
                zone_key: None,
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
            _source_zone_key: Option<&str>,
        ) {
            self.discoveries_sent.borrow_mut().push(event.clone());
        }

        fn send_zone_query(&self, position: &PlayerPosition, grace_entity_id: Option<u32>) {
            self.zone_queries_sent.borrow_mut().push(ZoneQueryRecord {
                position: position.clone(),
                grace_entity_id,
            });
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
}
