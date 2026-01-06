//! WebSocket protocol types
//!
//! This module contains the JSON message types used for communication
//! between the mod and the fog-tracker server. These types are
//! platform-independent and can be tested without Windows APIs.

use serde::{Deserialize, Serialize};

// =============================================================================
// DATA TYPES
// =============================================================================

/// Position data for discovery messages
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Position {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Position {
    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }
}

/// A propagated link from the server response
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PropagatedLink {
    pub source: String,
    pub target: String,
}

/// A fog gate exit from the current zone
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct FogExit {
    /// Target zone name, or "???" if not discovered
    pub target: String,
    /// How to get there (direction/description)
    #[serde(default)]
    pub description: String,
    /// If exit is from a different zone in the preexisting group
    pub from_zone: Option<String>,
}

/// Discovery statistics from the server
#[derive(Debug, Clone, Default, PartialEq, Deserialize, Serialize)]
pub struct DiscoveryStats {
    /// Number of discovered random links
    pub discovered: u32,
    /// Total number of random links
    pub total: u32,
}

// =============================================================================
// SERVER MESSAGES (mod → server)
// =============================================================================

/// Messages sent to the server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Authentication with mod token
    Auth { token: String },
    /// Discovery event (V2 protocol with positions)
    DiscoveryV2 {
        source_map_id: String,
        source_pos: Position,
        #[serde(skip_serializing_if = "Option::is_none")]
        source_play_region_id: Option<u32>,
        /// Source zone display name (from cached session state)
        #[serde(skip_serializing_if = "Option::is_none")]
        source_zone: Option<String>,
        /// Source zone key (from cached session state)
        #[serde(skip_serializing_if = "Option::is_none")]
        source_zone_id: Option<String>,
        target_map_id: String,
        target_pos: Position,
        #[serde(skip_serializing_if = "Option::is_none")]
        target_play_region_id: Option<u32>,
        warp_type: String,
        destination_entity_id: u32,
    },
    /// Query current zone (after fast travel)
    ZoneQuery {
        map_id: String,
        pos: Position,
        #[serde(skip_serializing_if = "Option::is_none")]
        play_region_id: Option<u32>,
        /// Entity ID of the grace being fast traveled to (enables precise zone lookup)
        #[serde(skip_serializing_if = "Option::is_none")]
        grace_entity_id: Option<u32>,
    },
    /// Pong response to server ping
    Pong,
    /// Upload recent logs to server
    UploadLogs { content: String },
    /// Game stats update (runes, kindling, deaths, play time)
    GameStatsUpdate {
        great_runes: Vec<String>,
        kindling_count: u32,
        death_count: u32,
        play_time_ms: u32,
    },
}

// =============================================================================
// SERVER RESPONSES (server → mod)
// =============================================================================

/// Messages received from the server
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerResponse {
    /// Authentication successful (with optional stats)
    AuthOk {
        #[serde(default)]
        stats: Option<DiscoveryStats>,
    },
    /// Authentication failed
    AuthError { message: String },
    /// Discovery acknowledged (V2 protocol)
    DiscoveryV2Ack {
        propagated: Vec<PropagatedLink>,
        current_zone: Option<String>,
        /// Zone key (e.g., "limgrave_stormhill")
        #[serde(default)]
        current_zone_id: Option<String>,
        #[serde(default)]
        exits: Vec<FogExit>,
        #[serde(default)]
        stats: DiscoveryStats,
        /// Zone scaling text (e.g., "Scaling: tier 1, previously 2")
        #[serde(default)]
        scaling: Option<String>,
    },
    /// Discovery broadcast from host (web UI manual discovery)
    Discovery {
        #[serde(default)]
        propagated: Vec<PropagatedLink>,
        #[serde(default)]
        stats: DiscoveryStats,
    },
    /// Zone query response
    ZoneQueryAck {
        zone: Option<String>,
        /// Zone key (e.g., "limgrave_stormhill")
        #[serde(default)]
        zone_id: Option<String>,
        #[serde(default)]
        exits: Vec<FogExit>,
        /// Zone scaling text (e.g., "Scaling: tier 1, previously 2")
        #[serde(default)]
        scaling: Option<String>,
    },
    /// Server ping (mod should respond with Pong)
    Ping,
    /// Error message from server
    Error { message: String },
    /// Upload logs acknowledgment
    UploadLogsAck {
        success: bool,
        #[serde(default)]
        message: Option<String>,
    },
    /// Game stats update acknowledged
    GameStatsUpdateAck,
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -------------------------------------------------------------------------
    // Position tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_position_serialize() {
        let pos = Position::new(100.5, 200.0, -50.25);
        let json = serde_json::to_string(&pos).unwrap();
        assert!(json.contains("100.5"));
        assert!(json.contains("200"));
        assert!(json.contains("-50.25"));
    }

    #[test]
    fn test_position_deserialize() {
        let json = r#"{"x": 10.0, "y": 20.0, "z": 30.0}"#;
        let pos: Position = serde_json::from_str(json).unwrap();
        assert_eq!(pos.x, 10.0);
        assert_eq!(pos.y, 20.0);
        assert_eq!(pos.z, 30.0);
    }

    // -------------------------------------------------------------------------
    // FogExit tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_fog_exit_full() {
        let json = r#"{"target": "Stormveil Castle", "description": "North gate", "from_zone": "Limgrave"}"#;
        let exit: FogExit = serde_json::from_str(json).unwrap();
        assert_eq!(exit.target, "Stormveil Castle");
        assert_eq!(exit.description, "North gate");
        assert_eq!(exit.from_zone, Some("Limgrave".to_string()));
    }

    #[test]
    fn test_fog_exit_minimal() {
        let json = r#"{"target": "???"}"#;
        let exit: FogExit = serde_json::from_str(json).unwrap();
        assert_eq!(exit.target, "???");
        assert_eq!(exit.description, ""); // default
        assert_eq!(exit.from_zone, None);
    }

    #[test]
    fn test_fog_exit_undiscovered() {
        let json = r#"{"target": "???", "description": "Through the fog wall"}"#;
        let exit: FogExit = serde_json::from_str(json).unwrap();
        assert_eq!(exit.target, "???");
        assert_eq!(exit.description, "Through the fog wall");
    }

    // -------------------------------------------------------------------------
    // DiscoveryStats tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_discovery_stats() {
        let json = r#"{"discovered": 42, "total": 100}"#;
        let stats: DiscoveryStats = serde_json::from_str(json).unwrap();
        assert_eq!(stats.discovered, 42);
        assert_eq!(stats.total, 100);
    }

    #[test]
    fn test_discovery_stats_default() {
        let stats = DiscoveryStats::default();
        assert_eq!(stats.discovered, 0);
        assert_eq!(stats.total, 0);
    }

    // -------------------------------------------------------------------------
    // ServerMessage tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_auth_message_serialize() {
        let msg = ServerMessage::Auth {
            token: "secret123".to_string(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"auth""#));
        assert!(json.contains(r#""token":"secret123""#));
    }

    #[test]
    fn test_discovery_v2_message_serialize() {
        let msg = ServerMessage::DiscoveryV2 {
            source_map_id: "m60_44_36_00".to_string(),
            source_pos: Position::new(100.0, 0.0, 100.0),
            source_play_region_id: Some(6044360),
            source_zone: Some("Limgrave".to_string()),
            source_zone_id: Some("limgrave".to_string()),
            target_map_id: "m10_00_00_00".to_string(),
            target_pos: Position::new(200.0, 0.0, 200.0),
            target_play_region_id: None,
            warp_type: "FOG".to_string(),
            destination_entity_id: 755890042,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"discovery_v2""#));
        assert!(json.contains(r#""source_map_id":"m60_44_36_00""#));
        assert!(json.contains(r#""warp_type":"FOG""#));
        assert!(json.contains(r#""destination_entity_id":755890042"#));
        // source_play_region_id should be present
        assert!(json.contains(r#""source_play_region_id":6044360"#));
        // source_zone and source_zone_id should be present
        assert!(json.contains(r#""source_zone":"Limgrave""#));
        assert!(json.contains(r#""source_zone_id":"limgrave""#));
        // target_play_region_id should be absent (skip_serializing_if)
        assert!(!json.contains("target_play_region_id"));
    }

    #[test]
    fn test_discovery_v2_message_serialize_no_source_zone() {
        let msg = ServerMessage::DiscoveryV2 {
            source_map_id: "m60_44_36_00".to_string(),
            source_pos: Position::new(100.0, 0.0, 100.0),
            source_play_region_id: None,
            source_zone: None,
            source_zone_id: None,
            target_map_id: "m10_00_00_00".to_string(),
            target_pos: Position::new(200.0, 0.0, 200.0),
            target_play_region_id: None,
            warp_type: "FOG".to_string(),
            destination_entity_id: 755890042,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"discovery_v2""#));
        // source_zone and source_zone_id should be absent (skip_serializing_if)
        assert!(!json.contains("source_zone"));
        assert!(!json.contains("source_zone_id"));
    }

    #[test]
    fn test_zone_query_message_serialize() {
        let msg = ServerMessage::ZoneQuery {
            map_id: "m60_44_36_00".to_string(),
            pos: Position::new(100.0, 0.0, 100.0),
            play_region_id: Some(6044360),
            grace_entity_id: Some(1042362951),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""map_id":"m60_44_36_00""#));
        assert!(json.contains(r#""grace_entity_id":1042362951"#));
    }

    #[test]
    fn test_zone_query_message_serialize_no_grace() {
        let msg = ServerMessage::ZoneQuery {
            map_id: "m60_44_36_00".to_string(),
            pos: Position::new(100.0, 0.0, 100.0),
            play_region_id: None,
            grace_entity_id: None,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        // grace_entity_id should be absent (skip_serializing_if)
        assert!(!json.contains("grace_entity_id"));
    }

    #[test]
    fn test_pong_message_serialize() {
        let msg = ServerMessage::Pong;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"pong"}"#);
    }

    #[test]
    fn test_game_stats_update_serialize() {
        let msg = ServerMessage::GameStatsUpdate {
            great_runes: vec!["Godrick".to_string(), "Radahn".to_string()],
            kindling_count: 5,
            death_count: 42,
            play_time_ms: 3600000,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"game_stats_update""#));
        assert!(json.contains(r#""great_runes":["Godrick","Radahn"]"#));
        assert!(json.contains(r#""kindling_count":5"#));
        assert!(json.contains(r#""death_count":42"#));
        assert!(json.contains(r#""play_time_ms":3600000"#));
    }

    #[test]
    fn test_game_stats_update_empty_runes() {
        let msg = ServerMessage::GameStatsUpdate {
            great_runes: vec![],
            kindling_count: 0,
            death_count: 10,
            play_time_ms: 1000,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""great_runes":[]"#));
        assert!(json.contains(r#""death_count":10"#));
    }

    // -------------------------------------------------------------------------
    // ServerResponse tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_auth_ok_deserialize() {
        // Without stats (backwards compatibility)
        let json = r#"{"type": "auth_ok"}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(resp, ServerResponse::AuthOk { stats: None });
    }

    #[test]
    fn test_auth_ok_with_stats() {
        let json = r#"{"type": "auth_ok", "stats": {"discovered": 42, "total": 100}}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(
            resp,
            ServerResponse::AuthOk {
                stats: Some(DiscoveryStats {
                    discovered: 42,
                    total: 100
                })
            }
        );
    }

    #[test]
    fn test_auth_error_deserialize() {
        let json = r#"{"type": "auth_error", "message": "Invalid token"}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(
            resp,
            ServerResponse::AuthError {
                message: "Invalid token".to_string()
            }
        );
    }

    #[test]
    fn test_discovery_v2_ack_full() {
        let json = r#"{
            "type": "discovery_v2_ack",
            "propagated": [{"source": "Limgrave", "target": "Stormveil Castle"}],
            "current_zone": "Stormveil Castle",
            "current_zone_id": "stormveil_castle",
            "exits": [{"target": "Limgrave", "description": "Main gate"}],
            "stats": {"discovered": 10, "total": 50},
            "scaling": "Scaling: tier 1, previously 2"
        }"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        match resp {
            ServerResponse::DiscoveryV2Ack {
                propagated,
                current_zone,
                current_zone_id,
                exits,
                stats,
                scaling,
            } => {
                assert_eq!(propagated.len(), 1);
                assert_eq!(propagated[0].source, "Limgrave");
                assert_eq!(propagated[0].target, "Stormveil Castle");
                assert_eq!(current_zone, Some("Stormveil Castle".to_string()));
                assert_eq!(current_zone_id, Some("stormveil_castle".to_string()));
                assert_eq!(exits.len(), 1);
                assert_eq!(exits[0].target, "Limgrave");
                assert_eq!(stats.discovered, 10);
                assert_eq!(stats.total, 50);
                assert_eq!(scaling, Some("Scaling: tier 1, previously 2".to_string()));
            }
            _ => panic!("Expected DiscoveryV2Ack"),
        }
    }

    #[test]
    fn test_discovery_v2_ack_minimal() {
        // Server may send minimal response with empty arrays
        let json = r#"{
            "type": "discovery_v2_ack",
            "propagated": [],
            "current_zone": null
        }"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        match resp {
            ServerResponse::DiscoveryV2Ack {
                propagated,
                current_zone,
                current_zone_id,
                exits,
                stats,
                scaling,
            } => {
                assert!(propagated.is_empty());
                assert!(current_zone.is_none());
                assert!(current_zone_id.is_none()); // default
                assert!(exits.is_empty()); // default
                assert_eq!(stats, DiscoveryStats::default()); // default
                assert!(scaling.is_none()); // default
            }
            _ => panic!("Expected DiscoveryV2Ack"),
        }
    }

    #[test]
    fn test_discovery_broadcast() {
        // Broadcast from web UI manual discovery
        let json = r#"{
            "type": "discovery",
            "propagated": [{"source": "A", "target": "B"}],
            "stats": {"discovered": 5, "total": 20}
        }"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        match resp {
            ServerResponse::Discovery { propagated, stats } => {
                assert_eq!(propagated.len(), 1);
                assert_eq!(stats.discovered, 5);
            }
            _ => panic!("Expected Discovery"),
        }
    }

    #[test]
    fn test_zone_query_ack() {
        let json = r#"{
            "type": "zone_query_ack",
            "zone": "Limgrave",
            "zone_id": "limgrave",
            "exits": [{"target": "???", "description": "North"}, {"target": "Stormveil", "description": "East"}],
            "scaling": "Scaling: tier 1"
        }"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        match resp {
            ServerResponse::ZoneQueryAck {
                zone,
                zone_id,
                exits,
                scaling,
            } => {
                assert_eq!(zone, Some("Limgrave".to_string()));
                assert_eq!(zone_id, Some("limgrave".to_string()));
                assert_eq!(exits.len(), 2);
                assert_eq!(scaling, Some("Scaling: tier 1".to_string()));
            }
            _ => panic!("Expected ZoneQueryAck"),
        }
    }

    #[test]
    fn test_zone_query_ack_unknown_zone() {
        let json = r#"{"type": "zone_query_ack", "zone": null}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        match resp {
            ServerResponse::ZoneQueryAck {
                zone,
                zone_id,
                exits,
                scaling,
            } => {
                assert!(zone.is_none());
                assert!(zone_id.is_none());
                assert!(exits.is_empty());
                assert!(scaling.is_none());
            }
            _ => panic!("Expected ZoneQueryAck"),
        }
    }

    #[test]
    fn test_ping_deserialize() {
        let json = r#"{"type": "ping"}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(resp, ServerResponse::Ping);
    }

    #[test]
    fn test_error_deserialize() {
        let json = r#"{"type": "error", "message": "Game not found"}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(
            resp,
            ServerResponse::Error {
                message: "Game not found".to_string()
            }
        );
    }

    #[test]
    fn test_game_stats_update_ack_deserialize() {
        let json = r#"{"type": "game_stats_update_ack"}"#;
        let resp: ServerResponse = serde_json::from_str(json).unwrap();
        assert_eq!(resp, ServerResponse::GameStatsUpdateAck);
    }

    // -------------------------------------------------------------------------
    // Round-trip tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_server_message_roundtrip() {
        let messages = vec![
            ServerMessage::Auth {
                token: "test".to_string(),
            },
            ServerMessage::Pong,
            ServerMessage::ZoneQuery {
                map_id: "m60_44_36_00".to_string(),
                pos: Position::new(1.0, 2.0, 3.0),
                play_region_id: None,
                grace_entity_id: None,
            },
            ServerMessage::ZoneQuery {
                map_id: "m60_42_36_00".to_string(),
                pos: Position::new(1.0, 2.0, 3.0),
                play_region_id: Some(1234),
                grace_entity_id: Some(1042362951),
            },
            ServerMessage::GameStatsUpdate {
                great_runes: vec!["Godrick".to_string(), "Radahn".to_string()],
                kindling_count: 5,
                death_count: 42,
                play_time_ms: 3600000,
            },
        ];

        for msg in messages {
            let json = serde_json::to_string(&msg).unwrap();
            let parsed: ServerMessage = serde_json::from_str(&json).unwrap();
            assert_eq!(msg, parsed);
        }
    }

    #[test]
    fn test_server_response_roundtrip() {
        let responses = vec![
            ServerResponse::AuthOk { stats: None },
            ServerResponse::AuthOk {
                stats: Some(DiscoveryStats {
                    discovered: 10,
                    total: 50,
                }),
            },
            ServerResponse::Ping,
            ServerResponse::AuthError {
                message: "bad".to_string(),
            },
            ServerResponse::Error {
                message: "oops".to_string(),
            },
            ServerResponse::GameStatsUpdateAck,
        ];

        for resp in responses {
            let json = serde_json::to_string(&resp).unwrap();
            let parsed: ServerResponse = serde_json::from_str(&json).unwrap();
            assert_eq!(resp, parsed);
        }
    }
}
