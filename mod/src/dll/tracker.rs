//! FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer
//!
//! This module provides the main DLL tracker that orchestrates:
//! - Game state reading (via eldenring module)
//! - Warp detection and discovery (via core::TrackerSession)
//! - Server communication (via WebSocket adapter)
//! - Debug logging and UI state

use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use super::log_reader::{read_recent_logs, LogReadError};

use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::animations::{get_animation_label, get_teleport_type};
use crate::core::constants::GreatRune;
use crate::core::entity_utils::is_fog_rando_entity;
use crate::core::io_traits::{
    ConnectionStatus as CoreConnectionStatus, DiscoveryResult, DiscoverySender, GameStats,
    ServerEvent, ServerEventReceiver, ZoneQueryResult,
};
use crate::core::protocol::{DiscoveryStats, FogExit};
use crate::core::session::{SessionEvent, TrackerSession};
use crate::core::traits::{GameStateReader, SpEffectChecker, WarpDetector};
use crate::core::types::SpEffectDebugInfo;
use crate::core::warp_tracker::DiscoveryEvent;
use crate::eldenring::{GameMan, GameState, SpEffect};

use super::config::Config;
use super::frame_state::FrameSnapshot;
use super::icon_atlas::IconAtlas;
use super::websocket::{ConnectionStatus as WsConnectionStatus, IncomingMessage, WebSocketClient};

// =============================================================================
// WEBSOCKET ADAPTER
// =============================================================================

/// Adapter that bridges WebSocketClient to the core I/O traits
///
/// This allows TrackerSession (platform-independent) to communicate
/// with the WebSocket client (platform-specific).
struct WebSocketAdapter<'a> {
    client: &'a mut WebSocketClient,
}

impl<'a> WebSocketAdapter<'a> {
    fn new(client: &'a mut WebSocketClient) -> Self {
        Self { client }
    }

    /// Convert WebSocket ConnectionStatus to core ConnectionStatus
    fn convert_status(status: WsConnectionStatus) -> CoreConnectionStatus {
        match status {
            WsConnectionStatus::Disconnected => CoreConnectionStatus::Disconnected,
            WsConnectionStatus::Connecting => CoreConnectionStatus::Connecting,
            WsConnectionStatus::Connected => CoreConnectionStatus::Connected,
            WsConnectionStatus::Reconnecting => CoreConnectionStatus::Reconnecting,
            WsConnectionStatus::Error => CoreConnectionStatus::Error,
        }
    }
}

impl DiscoverySender for WebSocketAdapter<'_> {
    fn is_connected(&self) -> bool {
        self.client.is_connected()
    }

    fn status(&self) -> CoreConnectionStatus {
        Self::convert_status(self.client.status())
    }

    fn send_discovery(
        &self,
        event: &DiscoveryEvent,
        source_zone: Option<&str>,
        source_zone_id: Option<&str>,
    ) {
        debug!(
            transport_type = event.transport_type,
            entry_map = event.entry.map_id_str,
            exit_map = event.exit.map_id_str,
            dest_entity = event.destination_entity_id,
            source_zone = ?source_zone,
            "[WS TX] discovery_v2"
        );
        self.client.send_discovery_v2(
            event.entry.map_id,
            event.entry.pos(),
            event.entry.play_region_id,
            source_zone.map(|s| s.to_string()),
            source_zone_id.map(|s| s.to_string()),
            event.exit.map_id,
            event.exit.pos(),
            event.exit.play_region_id,
            &event.transport_type,
            event.destination_entity_id,
        );
    }

    fn send_zone_query(
        &self,
        position: &crate::core::types::PlayerPosition,
        grace_entity_id: Option<u32>,
    ) {
        info!(
            map_id = position.map_id_str,
            pos = format!("({:.1}, {:.1}, {:.1})", position.x, position.y, position.z),
            grace_entity_id = ?grace_entity_id,
            "[ZONE] >>> QUERY SENT <<<"
        );
        self.client.send_zone_query(
            position.map_id,
            position.pos(),
            position.play_region_id,
            grace_entity_id,
        );
    }

    fn send_game_stats_update(&self, stats: &GameStats) {
        info!(
            runes = stats.great_runes.len(),
            kindling = stats.kindling_count,
            deaths = stats.death_count,
            igt_ms = stats.play_time_ms,
            "[STATS] >>> GAME STATS UPDATE <<<"
        );
        self.client.send_game_stats_update(
            stats.great_runes.clone(),
            stats.kindling_count,
            stats.death_count,
            stats.play_time_ms,
        );
    }
}

impl ServerEventReceiver for WebSocketAdapter<'_> {
    fn poll_event(&mut self) -> Option<ServerEvent> {
        self.client.poll().map(|msg| match msg {
            IncomingMessage::StatusChanged(status) => {
                ServerEvent::StatusChanged(Self::convert_status(status))
            }
            IncomingMessage::DiscoveryAck {
                propagated,
                current_zone,
                current_zone_id,
                exits,
                stats,
                scaling,
            } => ServerEvent::DiscoveryAck(DiscoveryResult {
                propagated,
                current_zone,
                current_zone_id,
                exits,
                stats,
                scaling,
            }),
            IncomingMessage::ZoneQueryAck {
                zone,
                zone_id,
                exits,
                scaling,
            } => ServerEvent::ZoneQueryAck(ZoneQueryResult {
                zone,
                zone_id,
                exits,
                scaling,
            }),
            IncomingMessage::Error(msg) => ServerEvent::Error(msg),
            IncomingMessage::Ping => {
                // Ping is auto-handled by WebSocketClient, but we still need to return something
                // We'll filter this out in the session
                ServerEvent::Error("ping".to_string())
            }
            IncomingMessage::UploadLogsAck { success, message } => {
                ServerEvent::UploadLogsAck { success, message }
            }
            IncomingMessage::StatsUpdated(stats) => ServerEvent::StatsUpdated(stats),
            IncomingMessage::GameStatsUpdateAck => ServerEvent::GameStatsUpdateAck,
        })
    }
}

// =============================================================================
// FOG RANDO TRACKER
// =============================================================================

/// Fog gate traversal tracking state
///
/// This is the main DLL-side tracker that:
/// - Owns the platform-specific game readers (GameState, SpEffect, GameMan)
/// - Owns the WebSocket client
/// - Delegates warp tracking to TrackerSession
/// - Handles debug logging (DLL-specific with tracing crate)
pub struct FogRandoTracker {
    // Platform-specific game readers
    game_state: GameState,
    sp_effect: SpEffect,
    game_man: GameMan,

    // Core tracking session (platform-independent)
    session: TrackerSession,

    // WebSocket client
    pub(crate) ws_client: WebSocketClient,

    // UI state
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    pub(crate) show_exits: bool,
    pub(crate) show_undiscovered_only: bool,
    pub(crate) config: Config,
    pub(crate) status_message: Option<(String, Instant)>,
    pub(crate) font_data: Option<Vec<u8>>,

    // Debug logging state (DLL-specific, uses tracing)
    last_logged_speffect_state: Option<(bool, Vec<u32>)>,
    last_speffect_log_time: Instant,
    last_logged_anim: Option<u32>,
    last_anim_log_time: Instant,
    last_logged_warp_requested: bool,

    // Previous game stats for change detection (send updates only when changed)
    previous_game_stats: Option<GameStats>,

    // Throttle for game stats checking (avoid scanning inventory every frame)
    last_game_stats_check: Instant,

    // Last time game stats were actually sent (for periodic updates)
    last_game_stats_send: Instant,

    // Icon atlas texture (loaded in initialize())
    pub(crate) icon_atlas: Option<IconAtlas>,

    // Path to log file (resolved during init, for log upload feature)
    log_file_path: Option<PathBuf>,
}

impl FogRandoTracker {
    /// Create a new FogRandoTracker instance
    pub fn new(hmodule: HINSTANCE) -> Option<Self> {
        info!("Initializing FogRandoTracker...");

        // Get DLL directory for loading resources
        let dll_dir = Config::get_dll_directory(hmodule)?;

        // Load configuration - REQUIRED (from DLL directory)
        let config = match Config::load(hmodule) {
            Ok(cfg) => cfg,
            Err(e) => {
                error!(error = %e, "Failed to load configuration");
                error!(
                    filename = Config::CONFIG_FILENAME,
                    "Please ensure config file exists next to the DLL"
                );
                return None;
            }
        };

        info!(
            toggle_ui = config.keybindings.toggle_ui.name(),
            "Keybindings loaded"
        );

        // Initialize game state reader
        let game_state = GameState::new();

        // Wait for the game to be loaded
        game_state.wait_for_game_loaded();

        // Initialize SpEffect reader for teleporter detection
        let sp_effect = SpEffect::new(game_state.base_addresses());

        // Initialize GameMan reader for warp detection
        let game_man = GameMan::new(game_state.base_addresses());

        // Install warp function hook for grace entity ID capture
        unsafe {
            let lua_warp = game_state.base_addresses().lua_warp;
            if let Err(e) = crate::eldenring::warp_hook::install(lua_warp) {
                error!(error = %e, "Failed to install warp hook (grace tracking may be limited)");
                // Continue without the hook - fall back to existing behavior
            }
        }

        info!("FogRandoTracker initialized!");

        // Initialize WebSocket client for server integration
        let mut ws_client = WebSocketClient::new(config.server.clone());
        if ws_client.is_enabled() {
            info!(
                url = %config.server.url,
                "Server integration enabled, connecting..."
            );
            ws_client.connect();
        } else {
            info!("Server integration disabled (missing url, token, or game_id in config)");
        }

        // Pre-load font data (will be used in initialize())
        let font_data = Self::load_font_data(&dll_dir, &config.overlay.font_path);

        // Resolve log file path (for log upload feature)
        let log_file_path = if config.logging.log_file.is_empty() {
            None
        } else {
            let path = PathBuf::from(&config.logging.log_file);
            if path.is_absolute() {
                Some(path)
            } else {
                Some(dll_dir.join(&config.logging.log_file))
            }
        };

        Some(Self {
            game_state,
            sp_effect,
            game_man,
            session: TrackerSession::new(),
            ws_client,
            show_ui: true,
            show_debug: false,
            show_exits: true,
            show_undiscovered_only: false,
            config,
            status_message: None,
            font_data,
            last_logged_speffect_state: None,
            last_speffect_log_time: Instant::now(),
            last_logged_anim: None,
            last_anim_log_time: Instant::now(),
            last_logged_warp_requested: false,
            previous_game_stats: None,
            last_game_stats_check: Instant::now(),
            last_game_stats_send: Instant::now(),
            icon_atlas: None,
            log_file_path,
        })
    }

    /// Per-frame update: process game state and handle events
    ///
    /// Called every frame by the render loop. This method:
    /// 1. Captures a FrameSnapshot with all game state readings upfront
    /// 2. Performs debug logging using the snapshot
    /// 3. Delegates warp detection to TrackerSession
    /// 4. Handles session events (discoveries, zone updates, etc.)
    /// 5. Sends game stats updates when they change
    pub fn update(&mut self) {
        // 1. Capture all game state in a single pass
        let snapshot = FrameSnapshot::capture(&self.game_state, &self.game_man);

        // 2. Debug logging (DLL-specific, uses tracing)
        // SpEffect debug is optimized with early return check
        self.log_speffect_debug(&snapshot);
        self.log_animation_debug(&snapshot);
        self.log_warp_debug(&snapshot);

        // 3. Create adapter for WebSocket communication
        let mut adapter = WebSocketAdapter::new(&mut self.ws_client);

        // 4. Delegate to TrackerSession using snapshot for both traits
        let events = self.session.update(&snapshot, &snapshot, &mut adapter);

        // 5. Handle session events
        for event in events {
            match event {
                SessionEvent::DiscoverySent(discovery) => {
                    info!(
                        transport_type = discovery.transport_type,
                        entry = discovery.entry.map_id_str,
                        exit = discovery.exit.map_id_str,
                        dest_entity = discovery.destination_entity_id,
                        "[WARP] >>> DISCOVERY SENT <<<"
                    );
                }
                SessionEvent::DiscoveryAcked(result) => {
                    info!(
                        propagated_count = result.propagated.len(),
                        zone = ?result.current_zone,
                        exit_count = result.exits.len(),
                        discovered = result.stats.discovered,
                        total = result.stats.total,
                        "Discovery acknowledged by server"
                    );
                }
                SessionEvent::ZoneQuerySent => {
                    debug!("[ZONE] Query sent, waiting for ack");
                }
                SessionEvent::ZoneUpdated(result) => {
                    // Clear the warp hook's captured grace ID now that the zone query is complete
                    crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                    info!(
                        zone = ?result.zone,
                        exit_count = result.exits.len(),
                        "[ZONE] >>> ZONE RESOLVED <<<"
                    );
                }
                SessionEvent::ConnectionChanged(status) => {
                    info!(status = ?status, "WebSocket status changed");
                    match status {
                        CoreConnectionStatus::Connected => {
                            self.set_status("Server connected".to_string());
                        }
                        CoreConnectionStatus::Error => {
                            if let Some(err) = self.ws_client.last_error() {
                                // Show user-friendly message for common HTTP errors
                                let detail = if err.contains("502") || err.contains("Bad Gateway") {
                                    "Maintenance".to_string()
                                } else {
                                    err.to_string()
                                };
                                self.set_status(format!("Server error: {}", detail));
                            }
                        }
                        CoreConnectionStatus::Reconnecting => {
                            self.set_status("Reconnecting to server...".to_string());
                        }
                        _ => {}
                    }
                }
                SessionEvent::ServerError(msg) => {
                    // Filter out ping "errors" (they're not real errors)
                    if msg != "ping" {
                        error!(error = %msg, "WebSocket error");
                    }
                }
                SessionEvent::LogsUploaded { success, message } => {
                    if success {
                        self.set_status("Logs uploaded successfully".to_string());
                    } else {
                        let msg = message.unwrap_or_else(|| "Unknown error".to_string());
                        self.set_status(format!("Log upload failed: {}", msg));
                    }
                }
                SessionEvent::StatsUpdated(stats) => {
                    debug!(
                        discovered = stats.discovered,
                        total = stats.total,
                        "[STATS] Stats updated (zone/exits preserved)"
                    );
                }
            }
        }

        // 6. Check for game stats changes and send updates if connected
        self.check_and_send_game_stats();
    }

    /// Check for game stats changes and send update if connected
    ///
    /// Sends updates when:
    /// - WebSocket is connected
    /// - Stats can be read (player is in-game)
    /// - Stats are not empty (player is in an active game session)
    /// - AND one of:
    ///   - Stats have meaningfully changed (runes, kindling, deaths)
    ///   - 10 seconds have elapsed since last send (to keep play_time_ms fresh)
    fn check_and_send_game_stats(&mut self) {
        // Don't check if not connected
        if !self.ws_client.is_connected() {
            return;
        }

        // Throttle: only scan inventory once per second (stats change infrequently)
        if self.last_game_stats_check.elapsed() < Duration::from_secs(1) {
            return;
        }
        self.last_game_stats_check = Instant::now();

        // Try to read current stats
        if let Some(current_stats) = self.read_current_game_stats() {
            // Skip empty stats (player not in active game session)
            if current_stats.is_empty() {
                return;
            }

            // Check if stats have meaningfully changed
            let meaningful_change = match &self.previous_game_stats {
                None => true, // First time, send initial stats
                Some(prev) => prev.has_meaningful_change(&current_stats),
            };

            // Also send periodically to keep play_time_ms fresh
            let periodic_update = self.last_game_stats_send.elapsed() >= Duration::from_secs(10);

            if meaningful_change || periodic_update {
                info!(
                    runes = ?current_stats.great_runes,
                    kindling = current_stats.kindling_count,
                    deaths = current_stats.death_count,
                    igt_ms = current_stats.play_time_ms,
                    periodic = periodic_update && !meaningful_change,
                    "[STATS] Sending game stats update"
                );

                // Send update to server
                self.ws_client.send_game_stats_update(
                    current_stats.great_runes.clone(),
                    current_stats.kindling_count,
                    current_stats.death_count,
                    current_stats.play_time_ms,
                );

                // Update tracking state
                self.previous_game_stats = Some(current_stats);
                self.last_game_stats_send = Instant::now();
            }
        }
        // If stats can't be read (player quit), don't update previous_stats
        // This prevents sending a "reset" when the player quits
    }

    /// Read current game stats from memory
    ///
    /// Returns None if any of the stats can't be read (player not in-game)
    fn read_current_game_stats(&self) -> Option<GameStats> {
        // Read all stats - all must succeed for a valid reading
        let great_runes = self.game_state.read_great_runes()?;
        let kindling_count = self.game_state.read_kindling_count()?;
        let death_count = self.game_state.read_deaths()?;
        let play_time_ms = self.game_state.read_igt()?;

        // Convert HashSet<GreatRune> to Vec<String>
        let rune_names: Vec<String> = great_runes
            .into_iter()
            .map(|r| format!("{:?}", r)) // Uses Debug impl: "Godrick", "Radahn", etc.
            .collect();

        Some(GameStats::new(
            rune_names,
            kindling_count,
            death_count,
            play_time_ms,
        ))
    }

    /// Set a status message that will be displayed temporarily
    pub fn set_status(&mut self, message: String) {
        self.status_message = Some((message, Instant::now()));
    }

    /// Get current status message if still valid (within 3 seconds)
    pub fn get_status(&self) -> Option<&str> {
        self.status_message.as_ref().and_then(|(msg, time)| {
            if time.elapsed() < Duration::from_secs(3) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    /// Upload recent logs to the server
    pub fn trigger_log_upload(&mut self) {
        let log_path = match &self.log_file_path {
            Some(path) => path,
            None => {
                self.set_status("No log file configured".to_string());
                return;
            }
        };

        if !self.ws_client.is_connected() {
            self.set_status("Not connected to server".to_string());
            return;
        }

        // Read last 5 minutes of logs
        let duration = Duration::from_secs(5 * 60);
        match read_recent_logs(log_path, duration) {
            Ok(content) => {
                info!(bytes = content.len(), "[LOG UPLOAD] Sending logs to server");
                self.ws_client.send_upload_logs(content);
                self.set_status("Uploading logs...".to_string());
            }
            Err(LogReadError::FileNotFound) => {
                self.set_status("Log file not found".to_string());
            }
            Err(LogReadError::EmptyFile) => {
                self.set_status("Log file is empty".to_string());
            }
            Err(LogReadError::NoRecentLogs) => {
                self.set_status("No logs in last 5 minutes".to_string());
            }
            Err(LogReadError::IoError(e)) => {
                error!(error = %e, "[LOG UPLOAD] IO error reading logs");
                self.set_status(format!("Error reading logs: {}", e));
            }
        }
    }

    /// Returns the player's current map_id and its string representation
    pub fn get_current_position(&self) -> Option<(u32, String)> {
        let pos = self.game_state.read_position()?;
        Some((pos.map_id, pos.map_id_str))
    }

    /// Get current zone name (from session state)
    pub fn current_zone(&self) -> Option<&str> {
        self.session.current_zone()
    }

    /// Get fog exits from current zone (from session state)
    pub fn current_exits(&self) -> &[FogExit] {
        self.session.exits()
    }

    /// Get discovery statistics (from session state)
    pub fn discovery_stats(&self) -> Option<&DiscoveryStats> {
        self.session.stats()
    }

    /// Get current zone scaling text (from session state)
    pub fn current_zone_scaling(&self) -> Option<&str> {
        self.session.current_zone_scaling()
    }

    /// Get the WebSocket connection status
    pub fn ws_status(&self) -> WsConnectionStatus {
        self.ws_client.status()
    }

    /// Check if server integration is enabled
    pub fn is_server_enabled(&self) -> bool {
        self.ws_client.is_enabled()
    }

    /// Get SpEffect debug info for the debug UI section
    pub fn get_speffect_debug(&self) -> SpEffectDebugInfo {
        self.sp_effect.get_debug_info()
    }

    /// Get the death count from game memory
    pub fn read_deaths(&self) -> Option<u32> {
        self.game_state.read_deaths()
    }

    /// Get the in-game time from game memory (in milliseconds)
    pub fn read_igt(&self) -> Option<u32> {
        self.game_state.read_igt()
    }

    /// Get the Great Runes count from game memory
    pub fn read_great_runes_count(&self) -> Option<u32> {
        self.game_state.read_great_runes_count()
    }

    /// Get the set of possessed Great Runes
    pub fn read_great_runes(&self) -> Option<HashSet<GreatRune>> {
        self.game_state.read_great_runes()
    }

    /// Get the Messmer's Kindling count from game memory
    pub fn read_kindling_count(&self) -> Option<u32> {
        self.game_state.read_kindling_count()
    }

    /// Log GameMan warp state changes (with deduplication)
    fn log_warp_debug(&mut self, snapshot: &FrameSnapshot) {
        let warp_requested = snapshot.is_warp_requested();

        if warp_requested != self.last_logged_warp_requested {
            let warp_info = snapshot.get_warp_info();
            if warp_requested {
                let dest_entity = warp_info
                    .as_ref()
                    .map(|w| w.destination_entity_id)
                    .unwrap_or(0);
                let dest_map = warp_info
                    .as_ref()
                    .map(|w| w.destination_map_id)
                    .unwrap_or(0);
                let cur_anim = snapshot.read_animation();
                let is_fog_rando = is_fog_rando_entity(dest_entity);
                let has_known_anim = cur_anim.and_then(get_teleport_type).is_some();

                // Always log warp requests at info level for diagnostics
                let target_grace = snapshot.get_target_grace_entity_id();
                info!(
                    dest_entity,
                    dest_map,
                    is_fog_rando,
                    cur_anim = cur_anim.unwrap_or(0),
                    has_known_anim,
                    target_grace,
                    "[GAMEMAN] >>> WARP REQUESTED <<<"
                );

                // Special warning for potential untracked Fog Rando warps
                if is_fog_rando && !has_known_anim {
                    if let Some(pos) = snapshot.read_position() {
                        warn!(
                            dest_entity,
                            map_id = pos.map_id_str,
                            x = format!("{:.1}", pos.x),
                            y = format!("{:.1}", pos.y),
                            z = format!("{:.1}", pos.z),
                            cur_anim = cur_anim.unwrap_or(0),
                            "[GAMEMAN] !!! FOG RANDO WARP WITHOUT KNOWN ANIMATION - possible back-to-entrance !!!"
                        );
                    }
                }
            } else {
                debug!("[GAMEMAN] Warp completed");
            }
            self.last_logged_warp_requested = warp_requested;
        }
    }

    /// Log animation changes (with deduplication)
    /// Only logs when animation changes or every 5 seconds as a heartbeat
    fn log_animation_debug(&mut self, snapshot: &FrameSnapshot) {
        let cur_anim = snapshot.read_animation();

        // Check if animation changed or 5 seconds elapsed
        let anim_changed = cur_anim != self.last_logged_anim;
        let heartbeat_due = self.last_anim_log_time.elapsed() >= Duration::from_secs(5);

        if anim_changed || heartbeat_due {
            match cur_anim {
                Some(anim_id) => {
                    let label = get_animation_label(anim_id);
                    debug!(anim_id, label, "[ANIM] cur_anim");
                }
                None => debug!("[ANIM] cur_anim: None (loading?)"),
            };
            self.last_logged_anim = cur_anim;
            self.last_anim_log_time = Instant::now();
        }
    }

    /// Log SpEffect debug info (with deduplication)
    /// Only logs when state changes or every 5 seconds as a heartbeat
    ///
    /// Optimized with early return: only does the expensive get_debug_info()
    /// scan if debug mode is enabled OR there's a state change to log.
    fn log_speffect_debug(&mut self, _snapshot: &FrameSnapshot) {
        let heartbeat_due = self.last_speffect_log_time.elapsed() >= Duration::from_secs(5);

        // Quick check: has teleport effect changed?
        let has_teleport_now = self.sp_effect.has_teleport_effect();
        let was_teleporting = self
            .last_logged_speffect_state
            .as_ref()
            .map(|(t, _)| *t)
            .unwrap_or(false);
        let teleport_changed = has_teleport_now != was_teleporting;

        // Early return: skip expensive scan if nothing to log
        // Only do full scan if: debug mode enabled OR teleport changed OR heartbeat due
        if !self.show_debug && !teleport_changed && !heartbeat_due {
            return;
        }

        // Now do the full scan (only when needed)
        let dbg = self.sp_effect.get_debug_info();
        let current_state = (dbg.has_teleport_effect, dbg.active_effects.clone());

        // Check if state changed
        let state_changed = self.last_logged_speffect_state.as_ref() != Some(&current_state);

        if state_changed || heartbeat_due {
            // Log pointer chain status
            let chain_status = if dbg.player_ins.is_some() && dbg.sp_effect_ctrl.is_some() {
                "OK"
            } else {
                "BROKEN"
            };

            debug!(
                chain = chain_status,
                player_ins = ?dbg.player_ins.map(|p| format!("0x{:X}", p)),
                sp_effect_ctrl = ?dbg.sp_effect_ctrl.map(|p| format!("0x{:X}", p)),
                "[SPEFFECT] Chain status"
            );

            // Log active effects
            if dbg.active_effects.is_empty() {
                debug!("[SPEFFECT] Active: (none)");
            } else {
                let effects_str: Vec<String> = dbg
                    .active_effects
                    .iter()
                    .map(|id| {
                        if *id == 4280 {
                            format!("*{}*", id) // Highlight teleport effect
                        } else {
                            id.to_string()
                        }
                    })
                    .collect();
                debug!(effects = %effects_str.join(", "), "[SPEFFECT] Active");
            }

            // Log teleport status change specifically
            if state_changed {
                if let Some((was_teleporting, _)) = &self.last_logged_speffect_state {
                    if *was_teleporting != dbg.has_teleport_effect {
                        if dbg.has_teleport_effect {
                            info!("[SPEFFECT] >>> TELEPORT EFFECT 4280 ACTIVATED <<<");
                        } else {
                            info!("[SPEFFECT] >>> TELEPORT EFFECT 4280 DEACTIVATED <<<");
                        }
                    }
                }
            }

            self.last_logged_speffect_state = Some(current_state);
            self.last_speffect_log_time = Instant::now();
        }
    }

    /// Load font data from file
    ///
    /// Resolution order:
    /// - Empty string: Use system default (C:\Windows\Fonts\segoeui.ttf)
    /// - Filename only (no path separators): Try Windows Fonts dir, then DLL dir
    /// - Relative path: Relative to DLL directory
    /// - Absolute path: Use directly
    fn load_font_data(dll_dir: &PathBuf, font_path: &str) -> Option<Vec<u8>> {
        use std::fs;
        use std::path::Path;

        const WINDOWS_FONTS_DIR: &str = r"C:\Windows\Fonts";
        const DEFAULT_SYSTEM_FONT: &str = "segoeui.ttf";

        // Determine which paths to try
        let paths_to_try: Vec<PathBuf> = if font_path.is_empty() {
            // Empty = use system default (Segoe UI)
            vec![Path::new(WINDOWS_FONTS_DIR).join(DEFAULT_SYSTEM_FONT)]
        } else {
            let path = Path::new(font_path);
            if path.is_absolute() {
                // Absolute path: use directly
                vec![path.to_path_buf()]
            } else if !font_path.contains('/') && !font_path.contains('\\') {
                // Filename only: try Windows Fonts first, then DLL dir
                vec![
                    Path::new(WINDOWS_FONTS_DIR).join(font_path),
                    dll_dir.join(font_path),
                ]
            } else {
                // Relative path with separators: DLL dir only
                vec![dll_dir.join(font_path)]
            }
        };

        // Try each path in order
        for full_path in &paths_to_try {
            if full_path.exists() {
                match fs::read(full_path) {
                    Ok(data) => {
                        info!(
                            path = %full_path.display(),
                            size = data.len(),
                            "Loaded font"
                        );
                        return Some(data);
                    }
                    Err(e) => {
                        error!(
                            path = %full_path.display(),
                            error = %e,
                            "Failed to read font file"
                        );
                    }
                }
            }
        }

        // No font found
        let tried = paths_to_try
            .iter()
            .map(|p| p.display().to_string())
            .collect::<Vec<_>>()
            .join(", ");
        warn!(tried_paths = %tried, "Font not found, using imgui default");
        None
    }
}
