// FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer

use std::path::PathBuf;
use std::time::{Duration, Instant};

use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::config::Config;
use crate::game_state::{
    GameManReader, GameState, PlayerPosition, SpEffectDebugInfo, SpEffectReader,
};
use crate::websocket::{
    ConnectionStatus, DiscoveryStats, FogExit, IncomingMessage, WebSocketClient,
};

// =============================================================================
// TELEPORT ANIMATION IDS
// =============================================================================

/// Known teleportation animation IDs
const ANIM_FOG_WALL: u32 = 60060;
const ANIM_BACK_TO_ENTRANCE: u32 = 60460;
const ANIM_WAYGATE: u32 = 60490;
const ANIM_SENDING_GATE_BLUE: u32 = 60470;
const ANIM_SENDING_GATE_RED: u32 = 60472;
const ANIM_MEDAL: u32 = 50340;
const ANIM_HORNED_REMAINS: u32 = 60010;
const ANIM_LIURNIA_TOWER_DOOR: u32 = 12202126;

/// Check if an animation ID corresponds to a teleportation and return its name
fn get_teleport_type(anim_id: u32) -> Option<&'static str> {
    match anim_id {
        ANIM_FOG_WALL => Some("FOG"),
        ANIM_BACK_TO_ENTRANCE => Some("BACK_TO_ENTRANCE"),
        ANIM_WAYGATE => Some("WAYGATE"),
        ANIM_SENDING_GATE_BLUE | ANIM_SENDING_GATE_RED => Some("SENDING_GATE"),
        ANIM_MEDAL => Some("MEDAL"),
        ANIM_HORNED_REMAINS => Some("HORNED_REMAINS"),
        ANIM_LIURNIA_TOWER_DOOR => Some("LIURNIA_TOWER_DOOR"),
        _ => None,
    }
}

/// Fog Gate Randomizer generates sequential entity IDs in this range
const FOG_RANDO_ENTITY_MIN: u32 = 755890000;
const FOG_RANDO_ENTITY_MAX: u32 = 755899999;

/// Check if an entity ID is from Fog Gate Randomizer
fn is_fog_rando_entity(entity_id: u32) -> bool {
    entity_id >= FOG_RANDO_ENTITY_MIN && entity_id <= FOG_RANDO_ENTITY_MAX
}

// =============================================================================
// PENDING WARP
// =============================================================================

/// Maximum time a pending warp can stay unresolved before being discarded
const WARP_TIMEOUT: Duration = Duration::from_secs(30);

/// Pending warp event (entry position recorded, waiting for exit)
#[derive(Clone, Debug)]
pub(crate) struct PendingWarp {
    entry: PlayerPosition,
    /// Entity ID of the warp destination (captured when warp_requested becomes true)
    destination_entity_id: u32,
    /// Transport type inferred from animation
    transport_type: &'static str,
    /// When this pending warp was created (for timeout detection)
    created_at: Instant,
}

// =============================================================================
// FOG RANDO TRACKER
// =============================================================================

/// Fog gate traversal tracking state
pub struct FogRandoTracker {
    game_state: GameState,
    sp_effect_reader: SpEffectReader,
    game_man_reader: GameManReader,
    /// Pending fog rando warp (entry recorded, waiting for exit)
    pending_warp: Option<PendingWarp>,
    /// Whether we were in a teleport animation last frame
    was_in_teleport_anim: bool,
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    pub(crate) config: Config,
    pub(crate) status_message: Option<(String, Instant)>,
    pub(crate) ws_client: WebSocketClient,
    /// Current zone name (resolved by server after fog traversal)
    pub(crate) current_zone: Option<String>,
    /// Fog exits from current zone (received from server)
    pub(crate) current_exits: Vec<FogExit>,
    /// Discovery statistics from server
    pub(crate) discovery_stats: Option<DiscoveryStats>,
    /// Whether position was readable last frame (to detect loading screens)
    was_position_readable: bool,
    /// Font data loaded from file (must persist for imgui)
    pub(crate) font_data: Option<Vec<u8>>,
    /// Last logged SpEffect debug state (to avoid duplicate logs)
    last_logged_speffect_state: Option<(bool, Vec<u32>)>,
    /// Last time we logged SpEffect debug info
    last_speffect_log_time: Instant,
    /// Last logged animation ID (to avoid duplicate logs)
    last_logged_anim: Option<u32>,
    /// Last time we logged animation debug info
    last_anim_log_time: Instant,
    /// Last logged warp_requested state
    last_logged_warp_requested: bool,
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
        let sp_effect_reader = SpEffectReader::new(game_state.base_addresses());

        // Initialize GameMan reader for warp detection
        let game_man_reader = GameManReader::new(game_state.base_addresses());

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
            sp_effect_reader,
            game_man_reader,
            pending_warp: None,
            was_in_teleport_anim: false,
            show_ui: true,
            show_debug: false,
            config,
            status_message: None,
            ws_client,
            current_zone: None,
            current_exits: Vec::new(),
            discovery_stats: None,
            was_position_readable: false,
            font_data,
            last_logged_speffect_state: None,
            last_speffect_log_time: Instant::now(),
            last_logged_anim: None,
            last_anim_log_time: Instant::now(),
            last_logged_warp_requested: false,
        })
    }

    /// Check for fog gate randomizer warps each frame
    ///
    /// Detection strategy:
    /// 1. Detect teleport animations (fog wall, waygate, sending gate, medal)
    /// 2. When animation starts → record entry position
    /// 3. Capture dest_entity_id when warp_requested becomes true (delayed for fog gates)
    /// 4. When animation ends + position readable → send discovery
    pub fn check_fog_traversal(&mut self) {
        // Log SpEffect debug info (with deduplication)
        self.log_speffect_debug();

        // Log animation changes (with deduplication)
        self.log_animation_debug();

        // Log GameMan warp state changes
        self.log_warp_debug();

        // Track loading screens - query zone info when exiting a loading screen
        // (position goes from None to Some). This handles teleportation, death, fast travel, etc.
        // But only if we don't have a pending warp (to avoid querying when we'll get info from discovery)
        let position_now_readable = self.game_state.read_position().is_some();
        if position_now_readable && !self.was_position_readable && self.pending_warp.is_none() {
            // Just exited a loading screen - query server for current zone
            if let Some(pos) = self.game_state.read_position() {
                if self.ws_client.is_connected() {
                    info!(
                        map_id = pos.map_id_str,
                        x = format!("{:.1}", pos.x),
                        y = format!("{:.1}", pos.y),
                        z = format!("{:.1}", pos.z),
                        "[ZONE_QUERY] Sending after loading screen"
                    );
                    self.ws_client
                        .send_zone_query(pos.map_id, pos.pos(), pos.play_region_id);
                }
            }
            // Clear temporarily while waiting for response
            self.current_zone = None;
            self.current_exits.clear();
        }
        self.was_position_readable = position_now_readable;

        // Check for pending warp timeout (prevents stale warps from hanging indefinitely)
        if let Some(ref pending) = self.pending_warp {
            if pending.created_at.elapsed() > WARP_TIMEOUT {
                warn!(
                    transport_type = pending.transport_type,
                    elapsed_secs = pending.created_at.elapsed().as_secs(),
                    "[WARP] Pending warp timed out, discarding"
                );
                self.pending_warp = None;
            }
        }

        // =========================================================================
        // ANIMATION-BASED TELEPORT DETECTION
        //
        // 1. Detect animation start → record entry position (dest_entity_id = 0)
        // 2. When warp_requested becomes true → capture dest_entity_id
        // 3. Detect animation end + position readable → send discovery
        // =========================================================================
        let cur_anim = self.game_state.read_animation();
        let is_in_teleport_anim = cur_anim.and_then(get_teleport_type).is_some();
        let transport_type = cur_anim.and_then(get_teleport_type).unwrap_or("OTHER");

        // Entry detection: animation just started
        if is_in_teleport_anim && !self.was_in_teleport_anim {
            if let Some(pos) = self.game_state.read_position() {
                info!(
                    transport_type,
                    map_id = pos.map_id_str,
                    x = format!("{:.1}", pos.x),
                    y = format!("{:.1}", pos.y),
                    z = format!("{:.1}", pos.z),
                    "[WARP] Teleport animation started"
                );
                self.pending_warp = Some(PendingWarp {
                    entry: pos,
                    destination_entity_id: 0, // Will be captured when warp_requested becomes true
                    transport_type,
                    created_at: Instant::now(),
                });
            } else {
                warn!(
                    transport_type,
                    "[WARP] Teleport animation started but position unreadable"
                );
            }
        }

        // Capture dest_entity_id when available (happens after animation start for fog gates)
        if let Some(ref mut pending) = self.pending_warp {
            if pending.destination_entity_id == 0 {
                let dest_entity_id = self.game_man_reader.get_destination_entity_id();
                if dest_entity_id != 0 {
                    pending.destination_entity_id = dest_entity_id;
                    debug!(dest_entity_id, "[WARP] Captured destination entity ID");
                }
            }
        }

        // Exit detection: animation ended + position readable
        if !is_in_teleport_anim && self.was_in_teleport_anim {
            if let Some(pending) = self.pending_warp.take() {
                if let Some(exit_pos) = self.game_state.read_position() {
                    info!(
                        entry = pending.entry.map_id_str,
                        exit = exit_pos.map_id_str,
                        transport_type = pending.transport_type,
                        dest_entity = pending.destination_entity_id,
                        "[WARP] Complete"
                    );
                    self.send_discovery(&pending, &exit_pos);
                } else {
                    // Position not readable yet (still loading) - keep pending
                    debug!(
                        entry = pending.entry.map_id_str,
                        "[WARP] Animation ended but position unreadable, waiting..."
                    );
                    self.pending_warp = Some(pending);
                }
            }
        }

        // Also check: if we have a pending warp with no animation and position is readable, send it
        // This handles cases where the animation ended while position was unreadable
        if self.pending_warp.is_some() && !is_in_teleport_anim && position_now_readable {
            if let Some(pending) = self.pending_warp.take() {
                if let Some(exit_pos) = self.game_state.read_position() {
                    info!(
                        entry = pending.entry.map_id_str,
                        exit = exit_pos.map_id_str,
                        transport_type = pending.transport_type,
                        dest_entity = pending.destination_entity_id,
                        "[WARP] Complete (delayed)"
                    );
                    self.send_discovery(&pending, &exit_pos);
                }
            }
        }

        self.was_in_teleport_anim = is_in_teleport_anim;
    }

    /// Send discovery event to server
    fn send_discovery(&mut self, pending: &PendingWarp, exit_pos: &PlayerPosition) {
        if self.ws_client.is_connected() {
            debug!(
                entry_map = pending.entry.map_id_str,
                entry_pos = format!("({:.1}, {:.1}, {:.1})", pending.entry.x, pending.entry.y, pending.entry.z),
                entry_region = ?pending.entry.play_region_id,
                exit_map = exit_pos.map_id_str,
                exit_pos_coords = format!("({:.1}, {:.1}, {:.1})", exit_pos.x, exit_pos.y, exit_pos.z),
                exit_region = ?exit_pos.play_region_id,
                dest_entity = pending.destination_entity_id,
                "[WARP] Sending discovery to server"
            );
            self.ws_client.send_discovery_v2(
                pending.entry.map_id,
                pending.entry.pos(),
                pending.entry.play_region_id,
                exit_pos.map_id,
                exit_pos.pos(),
                exit_pos.play_region_id,
                pending.transport_type,
                pending.destination_entity_id,
            );
        } else {
            warn!("[WARP] Not connected to server, discovery not sent");
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

    /// Poll the WebSocket client for incoming messages
    pub fn poll_websocket(&mut self) {
        while let Some(msg) = self.ws_client.poll() {
            match msg {
                IncomingMessage::StatusChanged(status) => {
                    info!(status = ?status, "WebSocket status changed");
                    match status {
                        ConnectionStatus::Connected => {
                            self.set_status("Server connected".to_string());
                        }
                        ConnectionStatus::Error => {
                            if let Some(err) = self.ws_client.last_error() {
                                self.set_status(format!("Server error: {}", err));
                            }
                        }
                        ConnectionStatus::Reconnecting => {
                            self.set_status("Reconnecting to server...".to_string());
                        }
                        _ => {}
                    }
                }
                IncomingMessage::DiscoveryAck {
                    propagated,
                    current_zone,
                    exits,
                    stats,
                } => {
                    info!(
                        propagated_count = propagated.len(),
                        zone = ?current_zone,
                        exit_count = exits.len(),
                        discovered = stats.discovered,
                        total = stats.total,
                        "Discovery acknowledged by server"
                    );
                    // Update current zone, exits, and stats
                    if current_zone.is_some() {
                        self.current_zone = current_zone;
                        self.current_exits = exits;
                    }
                    // Always update stats (even if zone resolution failed)
                    if stats.total > 0 {
                        self.discovery_stats = Some(stats);
                    }
                }
                IncomingMessage::ZoneQueryAck { zone, exits } => {
                    info!(
                        zone = ?zone,
                        exit_count = exits.len(),
                        "Zone query response"
                    );
                    if zone.is_some() {
                        self.current_zone = zone;
                        self.current_exits = exits;
                    }
                }
                IncomingMessage::Error(err) => {
                    error!(error = %err, "WebSocket error");
                }
                IncomingMessage::Ping => {
                    // Auto-handled by poll()
                }
            }
        }
    }

    /// Get the WebSocket connection status
    pub fn ws_status(&self) -> ConnectionStatus {
        self.ws_client.status()
    }

    /// Check if server integration is enabled
    pub fn is_server_enabled(&self) -> bool {
        self.ws_client.is_enabled()
    }

    /// Get SpEffect debug info for the debug UI section
    pub fn get_speffect_debug(&self) -> SpEffectDebugInfo {
        self.sp_effect_reader.get_debug_info()
    }

    /// Log GameMan warp state changes (with deduplication)
    fn log_warp_debug(&mut self) {
        let warp_requested = self.game_man_reader.is_warp_requested();

        if warp_requested != self.last_logged_warp_requested {
            let warp_info = self.game_man_reader.get_warp_info();
            if warp_requested {
                let dest_entity = warp_info
                    .as_ref()
                    .map(|w| w.destination_entity_id)
                    .unwrap_or(0);
                let dest_map = warp_info
                    .as_ref()
                    .map(|w| w.destination_map_id)
                    .unwrap_or(0);
                let cur_anim = self.game_state.read_animation();
                let is_fog_rando = is_fog_rando_entity(dest_entity);
                let has_known_anim = cur_anim.and_then(get_teleport_type).is_some();

                // Always log warp requests at info level for diagnostics
                info!(
                    dest_entity,
                    dest_map,
                    is_fog_rando,
                    cur_anim = cur_anim.unwrap_or(0),
                    has_known_anim,
                    "[GAMEMAN] >>> WARP REQUESTED <<<"
                );

                // Special warning for potential untracked Fog Rando warps
                if is_fog_rando && !has_known_anim {
                    if let Some(pos) = self.game_state.read_position() {
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
    fn log_animation_debug(&mut self) {
        let cur_anim = self.game_state.read_animation();

        // Check if animation changed or 5 seconds elapsed
        let anim_changed = cur_anim != self.last_logged_anim;
        let heartbeat_due = self.last_anim_log_time.elapsed() >= Duration::from_secs(5);

        if anim_changed || heartbeat_due {
            match cur_anim {
                Some(anim_id) => {
                    // Highlight known animations
                    let label = match anim_id {
                        60060 => "FOG_WALL",
                        60460 => "BACK_TO_ENTRANCE",
                        60490 => "WAYGATE",
                        60470 => "SENDING_GATE_BLUE",
                        60472 => "SENDING_GATE_RED",
                        50340 => "ITEM_USE_MEDAL",
                        50230 => "ITEM_USE_MEMORY",
                        60010 => "HORNED_REMAINS",
                        12202126 => "LIURNIA_TOWER_DOOR",
                        63000 => "SPAWN",
                        0 => "IDLE?",
                        _ => "",
                    };
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
    fn log_speffect_debug(&mut self) {
        let dbg = self.sp_effect_reader.get_debug_info();
        let current_state = (dbg.has_teleport_effect, dbg.active_effects.clone());

        // Check if state changed or 5 seconds elapsed
        let state_changed = self.last_logged_speffect_state.as_ref() != Some(&current_state);
        let heartbeat_due = self.last_speffect_log_time.elapsed() >= Duration::from_secs(5);

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
