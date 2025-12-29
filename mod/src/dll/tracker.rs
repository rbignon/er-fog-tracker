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

use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::animations::{get_animation_label, get_teleport_type};
use crate::core::constants::GreatRune;
use crate::core::entity_utils::is_fog_rando_entity;
use crate::core::io_traits::{
    ConnectionStatus as CoreConnectionStatus, DiscoveryResult, DiscoverySender, ServerEvent,
    ServerEventReceiver, ZoneQueryResult,
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

    fn send_discovery(&self, event: &DiscoveryEvent) {
        debug!(
            entry_map = event.entry.map_id_str,
            entry_pos = format!("({:.1}, {:.1}, {:.1})", event.entry.x, event.entry.y, event.entry.z),
            entry_region = ?event.entry.play_region_id,
            exit_map = event.exit.map_id_str,
            exit_pos = format!("({:.1}, {:.1}, {:.1})", event.exit.x, event.exit.y, event.exit.z),
            exit_region = ?event.exit.play_region_id,
            dest_entity = event.destination_entity_id,
            "[WARP] Sending discovery to server"
        );
        self.client.send_discovery_v2(
            event.entry.map_id,
            event.entry.pos(),
            event.entry.play_region_id,
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
            x = format!("{:.1}", position.x),
            y = format!("{:.1}", position.y),
            z = format!("{:.1}", position.z),
            grace_entity_id = ?grace_entity_id,
            "[ZONE_QUERY] Sending after loading screen"
        );
        self.client.send_zone_query(
            position.map_id,
            position.pos(),
            position.play_region_id,
            grace_entity_id,
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
                exits,
                stats,
                scaling,
            } => ServerEvent::DiscoveryAck(DiscoveryResult {
                propagated,
                current_zone,
                exits,
                stats,
                scaling,
            }),
            IncomingMessage::ZoneQueryAck {
                zone,
                exits,
                scaling,
            } => ServerEvent::ZoneQueryAck(ZoneQueryResult {
                zone,
                exits,
                scaling,
            }),
            IncomingMessage::Error(msg) => ServerEvent::Error(msg),
            IncomingMessage::Ping => {
                // Ping is auto-handled by WebSocketClient, but we still need to return something
                // We'll filter this out in the session
                ServerEvent::Error("ping".to_string())
            }
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
    pub(crate) config: Config,
    pub(crate) status_message: Option<(String, Instant)>,
    pub(crate) font_data: Option<Vec<u8>>,

    // Debug logging state (DLL-specific, uses tracing)
    last_logged_speffect_state: Option<(bool, Vec<u32>)>,
    last_speffect_log_time: Instant,
    last_logged_anim: Option<u32>,
    last_anim_log_time: Instant,
    last_logged_warp_requested: bool,

    // Debug: dump key items once to find Kindling param_id
    debug_items_dumped: bool,

    // Icon atlas texture (loaded in initialize())
    pub(crate) icon_atlas: Option<IconAtlas>,
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

        Some(Self {
            game_state,
            sp_effect,
            game_man,
            session: TrackerSession::new(),
            ws_client,
            show_ui: true,
            show_debug: false,
            show_exits: true,
            config,
            status_message: None,
            font_data,
            last_logged_speffect_state: None,
            last_speffect_log_time: Instant::now(),
            last_logged_anim: None,
            last_anim_log_time: Instant::now(),
            last_logged_warp_requested: false,
            debug_items_dumped: false,
            icon_atlas: None,
        })
    }

    /// Check for fog gate randomizer warps each frame
    ///
    /// This method:
    /// 1. Captures a FrameSnapshot with all game state readings upfront
    /// 2. Performs debug logging using the snapshot
    /// 3. Delegates warp detection to TrackerSession using the snapshot
    /// 4. Handles the resulting events (logging, status messages, etc.)
    pub fn check_fog_traversal(&mut self) {
        // 1. Capture all game state in a single pass
        let snapshot = FrameSnapshot::capture(&self.game_state, &self.game_man);

        // 2. Debug logging (DLL-specific, uses tracing)
        // SpEffect debug is optimized with early return check
        self.log_speffect_debug(&snapshot);
        self.log_animation_debug(&snapshot);
        self.log_warp_debug(&snapshot);

        // Debug: dump key items once to find Kindling param_id
        if !self.debug_items_dumped {
            if snapshot.read_position().is_some() {
                info!("[DEBUG] Dumping key items inventory...");
                self.debug_dump_key_items();
                self.debug_items_dumped = true;
            }
        }

        // 3. Create adapter for WebSocket communication
        let mut adapter = WebSocketAdapter::new(&mut self.ws_client);

        // 4. Delegate to TrackerSession using snapshot for both traits
        // Debug: log warp detection state
        if snapshot.is_warp_requested() {
            debug!(
                warp_requested = snapshot.is_warp_requested(),
                target_grace = snapshot.get_target_grace_entity_id(),
                has_pending_warp = self.session.has_pending_warp(),
                "[SESSION] Pre-update warp state"
            );
        }
        let events = self.session.update(&snapshot, &snapshot, &mut adapter);

        // 5. Handle session events
        for event in events {
            match event {
                SessionEvent::DiscoverySent(discovery) => {
                    info!(
                        entry = discovery.entry.map_id_str,
                        exit = discovery.exit.map_id_str,
                        transport_type = discovery.transport_type,
                        dest_entity = discovery.destination_entity_id,
                        "[WARP] Complete"
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
                    // Clear the warp hook's captured grace ID after it's been used
                    crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                }
                SessionEvent::ZoneUpdated(result) => {
                    info!(
                        zone = ?result.zone,
                        exit_count = result.exits.len(),
                        "Zone query response"
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
                                self.set_status(format!("Server error: {}", err));
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
            }
        }
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

    /// Debug: dump all key items to find the correct Kindling param_id
    pub fn debug_dump_key_items(&self) {
        self.game_state.debug_dump_key_items()
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
