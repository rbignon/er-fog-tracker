// FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer

use std::path::PathBuf;
use std::time::{Duration, Instant};

use windows::Win32::Foundation::HINSTANCE;

use crate::config::Config;
use crate::game_state::{
    GameManReader, GameState, PlayerPosition, SpEffectDebugInfo, SpEffectReader,
};
use crate::websocket::{
    ConnectionStatus, DiscoveryStats, FogExit, IncomingMessage, WebSocketClient,
};

// =============================================================================
// FOG GATE RANDOMIZER ENTITY RANGE
// =============================================================================

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

/// Pending warp event (entry position recorded, waiting for exit)
#[derive(Clone, Debug)]
pub(crate) struct PendingWarp {
    entry: PlayerPosition,
    /// Entity ID of the warp destination (755890xxx for fog rando warps)
    destination_entity_id: u32,
    /// Inferred transport type (for logging only)
    transport_type: &'static str,
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
    /// Previous warp_requested state (edge detection)
    was_warp_requested: bool,
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
        println!("Initializing FogRandoTracker...");

        // Get DLL directory for loading resources
        let dll_dir = Config::get_dll_directory(hmodule)?;

        // Load configuration - REQUIRED (from DLL directory)
        let config = match Config::load(hmodule) {
            Ok(cfg) => cfg,
            Err(e) => {
                eprintln!("Failed to load configuration: {}", e);
                eprintln!(
                    "Please ensure '{}' exists next to the DLL.",
                    Config::CONFIG_FILENAME
                );
                return None;
            }
        };

        println!(
            "Keybindings: Toggle UI={}",
            config.keybindings.toggle_ui.name()
        );

        // Initialize game state reader
        let game_state = GameState::new();

        // Wait for the game to be loaded
        game_state.wait_for_game_loaded();

        // Initialize SpEffect reader for teleporter detection
        let sp_effect_reader = SpEffectReader::new(game_state.base_addresses());

        // Initialize GameMan reader for warp detection
        let game_man_reader = GameManReader::new(game_state.base_addresses());

        println!("FogRandoTracker initialized!");

        // Initialize WebSocket client for server integration
        let mut ws_client = WebSocketClient::new(config.server.clone());
        if ws_client.is_enabled() {
            println!(
                "Server integration enabled, connecting to {}...",
                config.server.url
            );
            ws_client.connect();
        } else {
            println!("Server integration disabled (missing url, token, or game_id in config)");
        }

        // Pre-load font data (will be used in initialize())
        let font_data = Self::load_font_data(&dll_dir, &config.overlay.font_path);

        Some(Self {
            game_state,
            sp_effect_reader,
            game_man_reader,
            pending_warp: None,
            was_warp_requested: false,
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
    /// Simplified detection: a warp is relevant if dest_entity_id is in the
    /// Fog Gate Randomizer range (755890000-755899999). This avoids complex
    /// animation/SpEffect detection and eliminates false positives from deaths.
    pub fn check_fog_traversal(&mut self) {
        // Log SpEffect debug info (with deduplication)
        self.log_speffect_debug();

        // Log animation changes (with deduplication)
        self.log_animation_debug();

        // Log GameMan warp state changes
        self.log_warp_debug();

        // Track loading screens - clear zone info when exiting a loading screen
        // (position goes from None to Some). This handles teleportation, death, fast travel, etc.
        let position_now_readable = self.game_state.read_position().is_some();
        if position_now_readable && !self.was_position_readable {
            // Just exited a loading screen - clear current zone until we get new info from server
            self.current_zone = None;
            self.current_exits.clear();
        }
        self.was_position_readable = position_now_readable;

        // =========================================================================
        // FOG GATE RANDOMIZER WARP DETECTION
        //
        // Simple logic: when warp_requested becomes true and dest_entity_id is
        // in the fog rando range (755890000-755899999), record entry position.
        // When warp completes (warp_requested = false + position readable), send.
        // =========================================================================
        let warp_requested = self.game_man_reader.is_warp_requested();
        let dest_entity_id = self.game_man_reader.get_destination_entity_id();

        if warp_requested && !self.was_warp_requested {
            // Warp just started - check if it's a fog rando warp
            if is_fog_rando_entity(dest_entity_id) {
                if let Some(pos) = self.game_state.read_position() {
                    let transport_type = self.infer_transport_type();
                    println!(
                        "[WARP] Fog rando warp detected! type={} dest_entity={} entry=[{}] pos=({:.1}, {:.1}, {:.1})",
                        transport_type, dest_entity_id, pos.map_id_str, pos.x, pos.y, pos.z
                    );
                    self.pending_warp = Some(PendingWarp {
                        entry: pos,
                        destination_entity_id: dest_entity_id,
                        transport_type,
                    });
                } else {
                    println!(
                        "[WARP] WARNING: Fog rando warp detected but position unreadable! dest_entity={}",
                        dest_entity_id
                    );
                }
            }
        } else if !warp_requested && self.was_warp_requested {
            // Warp just completed - send discovery if we have a pending warp
            if let Some(pending) = self.pending_warp.take() {
                if let Some(exit_pos) = self.game_state.read_position() {
                    println!(
                        "[WARP] Complete: {} → {} (type={}, dest_entity={})",
                        pending.entry.map_id_str,
                        exit_pos.map_id_str,
                        pending.transport_type,
                        pending.destination_entity_id
                    );
                    self.send_discovery(&pending, &exit_pos);
                } else {
                    println!(
                        "[WARP] WARNING: Warp completed but exit position unreadable! Entry was at {}",
                        pending.entry.map_id_str
                    );
                }
            }
        }

        self.was_warp_requested = warp_requested;
    }

    /// Infer transport type from current animation (best-effort, for logging only)
    fn infer_transport_type(&self) -> &'static str {
        match self.game_state.read_animation() {
            Some(60060) => "FOG",
            Some(60490) => "WAYGATE",
            Some(60470) | Some(60472) => "SENDING_GATE",
            Some(50340) => "MEDAL",
            _ => "OTHER", // coffin, scripted events, etc.
        }
    }

    /// Send discovery event to server
    fn send_discovery(&mut self, pending: &PendingWarp, exit_pos: &PlayerPosition) {
        if self.ws_client.is_connected() {
            println!(
                "[WARP] Sending to server: {} ({:.1}, {:.1}, {:.1}) region={:?} → {} ({:.1}, {:.1}, {:.1}) region={:?} dest_entity={}",
                pending.entry.map_id_str,
                pending.entry.x, pending.entry.y, pending.entry.z,
                pending.entry.play_region_id,
                exit_pos.map_id_str,
                exit_pos.x, exit_pos.y, exit_pos.z,
                exit_pos.play_region_id,
                pending.destination_entity_id
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
            println!("[WARP] Not connected to server, discovery not sent");
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
                    println!("WebSocket status: {:?}", status);
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
                    println!(
                        "Discovery acknowledged by server ({} propagated, zone={:?}, {} exits, {}/{} discovered)",
                        propagated.len(),
                        current_zone,
                        exits.len(),
                        stats.discovered,
                        stats.total
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
                IncomingMessage::Error(err) => {
                    eprintln!("WebSocket error: {}", err);
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
                println!(
                    "[GAMEMAN] >>> WARP REQUESTED <<< dest_entity={} dest_map={}",
                    warp_info
                        .as_ref()
                        .map(|w| w.destination_entity_id)
                        .unwrap_or(0),
                    warp_info
                        .as_ref()
                        .map(|w| w.destination_map_id)
                        .unwrap_or(0)
                );
            } else {
                println!("[GAMEMAN] Warp completed");
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
                        60060 => " (FOG_WALL)",
                        60490 => " (WAYGATE)",
                        60470 => " (SENDING_GATE_BLUE)",
                        60472 => " (SENDING_GATE_RED)",
                        50340 => " (ITEM_USE_MEDAL)",
                        50230 => " (ITEM_USE_MEMORY)",
                        63000 => " (SPAWN)",
                        0 => " (IDLE?)",
                        _ => "",
                    };
                    println!("[ANIM] cur_anim: {}{}", anim_id, label);
                }
                None => println!("[ANIM] cur_anim: None (loading?)"),
            };
            self.last_logged_anim = cur_anim;
            self.last_anim_log_time = Instant::now();
        }
    }

    /// Log SpEffect debug info (with deduplication)
    /// Only logs when state changes or every 5 seconds as a heartbeat
    fn log_speffect_debug(&mut self) {
        let debug = self.sp_effect_reader.get_debug_info();
        let current_state = (debug.has_teleport_effect, debug.active_effects.clone());

        // Check if state changed or 5 seconds elapsed
        let state_changed = self.last_logged_speffect_state.as_ref() != Some(&current_state);
        let heartbeat_due = self.last_speffect_log_time.elapsed() >= Duration::from_secs(5);

        if state_changed || heartbeat_due {
            // Log pointer chain status
            let chain_status = if debug.player_ins.is_some() && debug.sp_effect_ctrl.is_some() {
                "OK"
            } else {
                "BROKEN"
            };

            println!(
                "[SPEFFECT] Chain: {} | PlayerIns: {:?} | SpEffCtrl: {:?}",
                chain_status,
                debug.player_ins.map(|p| format!("0x{:X}", p)),
                debug.sp_effect_ctrl.map(|p| format!("0x{:X}", p)),
            );

            // Log active effects
            if debug.active_effects.is_empty() {
                println!("[SPEFFECT] Active: (none)");
            } else {
                let display: Vec<String> = debug
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
                println!("[SPEFFECT] Active: [{}]", display.join(", "));
            }

            // Log teleport status change specifically
            if state_changed {
                if let Some((was_teleporting, _)) = &self.last_logged_speffect_state {
                    if *was_teleporting != debug.has_teleport_effect {
                        if debug.has_teleport_effect {
                            println!("[SPEFFECT] >>> TELEPORT EFFECT 4280 ACTIVATED <<<");
                        } else {
                            println!("[SPEFFECT] >>> TELEPORT EFFECT 4280 DEACTIVATED <<<");
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
                        println!(
                            "Loaded font from: {} ({} bytes)",
                            full_path.display(),
                            data.len()
                        );
                        return Some(data);
                    }
                    Err(e) => {
                        eprintln!("Failed to read font file {}: {}", full_path.display(), e);
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
        eprintln!("Font not found (tried: {}). Using imgui default.", tried);
        None
    }
}
