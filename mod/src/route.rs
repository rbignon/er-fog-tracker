// Fog traversal event data structures

use serde::Serialize;

// =============================================================================
// FOG TRAVERSAL EVENTS
// =============================================================================

/// Fog wall traversal event with entry and exit zones
#[derive(Clone, Debug, Serialize)]
pub struct FogEvent {
    /// Entry zone name (human-readable)
    pub entry_zone_name: String,
    /// Exit zone name (human-readable)
    pub exit_zone_name: String,
    /// Timestamp when entering fog (milliseconds from start)
    pub entry_timestamp_ms: u64,
    /// Timestamp when exiting fog (milliseconds from start)
    pub exit_timestamp_ms: u64,
}

/// Pending fog event (entry recorded, waiting for exit)
#[derive(Clone, Debug)]
pub struct PendingFogEvent {
    pub entry_zone_name: String,
    pub entry_timestamp_ms: u64,
}
