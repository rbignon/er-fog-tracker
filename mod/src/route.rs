// Fog traversal event data structures

use serde::Serialize;

// =============================================================================
// FOG TRAVERSAL EVENTS
// =============================================================================

/// Fog wall traversal event with entry and exit positions
#[derive(Clone, Debug, Serialize)]
pub struct FogEvent {
    /// Entry position - Global X coordinate before entering fog
    pub entry_x: f32,
    /// Entry position - Global Y coordinate (altitude)
    pub entry_y: f32,
    /// Entry position - Global Z coordinate
    pub entry_z: f32,
    /// Entry position - Map ID as string
    pub entry_map_id_str: String,
    /// Entry position - Zone name (human-readable)
    pub entry_zone_name: String,
    /// Exit position - Global X coordinate after exiting fog
    pub exit_x: f32,
    /// Exit position - Global Y coordinate (altitude)
    pub exit_y: f32,
    /// Exit position - Global Z coordinate
    pub exit_z: f32,
    /// Exit position - Map ID as string
    pub exit_map_id_str: String,
    /// Exit position - Zone name (human-readable)
    pub exit_zone_name: String,
    /// Timestamp when entering fog (milliseconds from start)
    pub entry_timestamp_ms: u64,
    /// Timestamp when exiting fog (milliseconds from start)
    pub exit_timestamp_ms: u64,
}

/// Pending fog event (entry recorded, waiting for exit)
#[derive(Clone, Debug)]
pub struct PendingFogEvent {
    pub entry_x: f32,
    pub entry_y: f32,
    pub entry_z: f32,
    pub entry_map_id_str: String,
    pub entry_zone_name: String,
    pub entry_timestamp_ms: u64,
}
