// FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer

use std::path::PathBuf;
use std::time::{Duration, Instant};

use windows::Win32::Foundation::HINSTANCE;

use crate::config::Config;
use crate::game_state::{
    GameState, PlayerPosition, SpEffectDebugInfo, SpEffectReader, TeleportType,
};
use crate::websocket::{
    ConnectionStatus, DiscoveryStats, FogExit, IncomingMessage, WebSocketClient,
};

// =============================================================================
// PENDING EVENT
// =============================================================================

/// Pending teleport event (entry position recorded, waiting for exit)
#[derive(Clone, Debug)]
pub(crate) struct PendingEvent {
    entry: PlayerPosition,
}

// =============================================================================
// FOG RANDO TRACKER
// =============================================================================

/// Fog gate traversal tracking state
pub struct FogRandoTracker {
    game_state: GameState,
    sp_effect_reader: SpEffectReader,
    // Teleport event state tracking (per TeleportType)
    pub(crate) was_in_fog: bool,
    pub(crate) pending_fog: Option<PendingEvent>,
    was_in_waygate: bool,
    pending_waygate: Option<PendingEvent>,
    was_using_medal: bool,
    pending_medal: Option<PendingEvent>,
    was_in_coffin: bool,
    pending_coffin: Option<PendingEvent>,
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
    /// Last known map_id (to detect teleportation)
    last_map_id: Option<u32>,
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
            // Teleport event state tracking
            was_in_fog: false,
            pending_fog: None,
            was_in_waygate: false,
            pending_waygate: None,
            was_using_medal: false,
            pending_medal: None,
            was_in_coffin: false,
            pending_coffin: None,
            show_ui: true,
            show_debug: false,
            config,
            status_message: None,
            ws_client,
            current_zone: None,
            current_exits: Vec::new(),
            discovery_stats: None,
            last_map_id: None,
            font_data,
            last_logged_speffect_state: None,
            last_speffect_log_time: Instant::now(),
            last_logged_anim: None,
            last_anim_log_time: Instant::now(),
        })
    }

    /// Check for fog wall and teleporter traversals each frame
    pub fn check_fog_traversal(&mut self) {
        // Log SpEffect debug info (with deduplication)
        self.log_speffect_debug();

        // Log animation changes (with deduplication)
        self.log_animation_debug();

        // Track map changes for context (but don't clear exits here anymore)
        if let Some(pos) = self.game_state.read_position() {
            self.last_map_id = Some(pos.map_id);
        }

        // =========================================================================
        // FOG WALL DETECTION
        // =========================================================================
        let is_fog = self.game_state.is_in_animation(TeleportType::FogWall);

        if is_fog && !self.was_in_fog {
            self.on_event_entry(TeleportType::FogWall);
        } else if self.pending_fog.is_some() && !is_fog {
            self.on_event_exit(TeleportType::FogWall);
        }
        self.was_in_fog = is_fog;

        // =========================================================================
        // WAYGATE / SENDING GATE DETECTION
        // =========================================================================
        let is_waygate = self.game_state.is_in_animation(TeleportType::Waygate);

        if is_waygate && !self.was_in_waygate {
            self.on_event_entry(TeleportType::Waygate);
        } else if self.pending_waygate.is_some() && !is_waygate {
            self.on_event_exit(TeleportType::Waygate);
        }
        self.was_in_waygate = is_waygate;

        // =========================================================================
        // MEDAL DETECTION (animation + SpEffect)
        // =========================================================================
        let is_medal = self.game_state.is_in_animation(TeleportType::Medal)
            && self.sp_effect_reader.has_event_effect(TeleportType::Medal);

        if is_medal && !self.was_using_medal {
            self.on_event_entry(TeleportType::Medal);
        } else if self.pending_medal.is_some() && !is_medal {
            self.on_event_exit(TeleportType::Medal);
        }
        self.was_using_medal = is_medal;

        // =========================================================================
        // COFFIN DETECTION (SpEffect only, no animation)
        // =========================================================================
        let is_coffin = self.sp_effect_reader.has_event_effect(TeleportType::Coffin);

        if is_coffin && !self.was_in_coffin {
            self.on_event_entry(TeleportType::Coffin);
        } else if self.pending_coffin.is_some() && !is_coffin {
            self.on_event_exit(TeleportType::Coffin);
        }
        self.was_in_coffin = is_coffin;
    }

    /// Handle teleport event entry (start of animation/SpEffect)
    fn on_event_entry(&mut self, event_type: TeleportType) {
        if let Some(pos) = self.game_state.read_position() {
            let name = event_type.name();
            println!(
                "[{}] Entry detected [{}] pos=({:.1}, {:.1}, {:.1}) region={:?}",
                name, pos.map_id_str, pos.x, pos.y, pos.z, pos.play_region_id
            );

            let pending = PendingEvent { entry: pos };
            match event_type {
                TeleportType::FogWall => self.pending_fog = Some(pending),
                TeleportType::Waygate => self.pending_waygate = Some(pending),
                TeleportType::Medal => self.pending_medal = Some(pending),
                TeleportType::Coffin => self.pending_coffin = Some(pending),
            }
        }
    }

    /// Handle teleport event exit (end of animation/SpEffect, position available)
    fn on_event_exit(&mut self, event_type: TeleportType) {
        if let Some(exit_pos) = self.game_state.read_position() {
            let entry = match event_type {
                TeleportType::FogWall => self.pending_fog.take().map(|p| p.entry),
                TeleportType::Waygate => self.pending_waygate.take().map(|p| p.entry),
                TeleportType::Medal => self.pending_medal.take().map(|p| p.entry),
                TeleportType::Coffin => self.pending_coffin.take().map(|p| p.entry),
            };

            if let Some(entry) = entry {
                let name = event_type.name();
                println!(
                    "[{}] Exit detected [{}] pos=({:.1}, {:.1}, {:.1}) region={:?}",
                    name,
                    exit_pos.map_id_str,
                    exit_pos.x,
                    exit_pos.y,
                    exit_pos.z,
                    exit_pos.play_region_id
                );
                println!(
                    "[{}] Traversal complete: {} → {}",
                    name, entry.map_id_str, exit_pos.map_id_str
                );

                self.send_discovery(event_type, &entry, &exit_pos);
            }
        }
    }

    /// Send discovery event to server (shared logic for all teleport types)
    fn send_discovery(
        &mut self,
        event_type: TeleportType,
        entry: &PlayerPosition,
        exit_pos: &PlayerPosition,
    ) {
        let name = event_type.name();
        if self.ws_client.is_connected() {
            println!(
                "[{}] Sending to server: {} ({:.1}, {:.1}, {:.1}) region={:?} → {} ({:.1}, {:.1}, {:.1}) region={:?}",
                name,
                entry.map_id_str,
                entry.x, entry.y, entry.z,
                entry.play_region_id,
                exit_pos.map_id_str,
                exit_pos.x, exit_pos.y, exit_pos.z,
                exit_pos.play_region_id
            );
            self.ws_client.send_discovery_v2(
                entry.map_id,
                entry.pos(),
                entry.play_region_id,
                exit_pos.map_id,
                exit_pos.pos(),
                exit_pos.play_region_id,
            );
        } else {
            println!("[{}] Not connected to server, discovery not sent", name);
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

    /// Log animation changes (with deduplication)
    /// Only logs when animation changes or every 5 seconds as a heartbeat
    fn log_animation_debug(&mut self) {
        let cur_anim = self.game_state.read_animation();

        // Check if animation changed or 5 seconds elapsed
        let anim_changed = cur_anim != self.last_logged_anim;
        let heartbeat_due = self.last_anim_log_time.elapsed() >= Duration::from_secs(5);

        if anim_changed || heartbeat_due {
            let msg = match cur_anim {
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
                    format!("[ANIM] cur_anim: {}{}", anim_id, label)
                }
                None => "[ANIM] cur_anim: None (loading?)".to_string(),
            };
            println!("{}", msg);
            self.ws_client.send_debug_log(&msg);
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

            let chain_msg = format!(
                "[SPEFFECT] Chain: {} | PlayerIns: {:?} | SpEffCtrl: {:?}",
                chain_status,
                debug.player_ins.map(|p| format!("0x{:X}", p)),
                debug.sp_effect_ctrl.map(|p| format!("0x{:X}", p)),
            );
            println!("{}", chain_msg);
            self.ws_client.send_debug_log(&chain_msg);

            // Log active effects
            let effects_msg = if debug.active_effects.is_empty() {
                "[SPEFFECT] Active: (none)".to_string()
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
                format!("[SPEFFECT] Active: [{}]", display.join(", "))
            };
            println!("{}", effects_msg);
            self.ws_client.send_debug_log(&effects_msg);

            // Log teleport status change specifically
            if state_changed {
                if let Some((was_teleporting, _)) = &self.last_logged_speffect_state {
                    if *was_teleporting != debug.has_teleport_effect {
                        let tp_msg = if debug.has_teleport_effect {
                            "[SPEFFECT] >>> TELEPORT EFFECT 4280 ACTIVATED <<<"
                        } else {
                            "[SPEFFECT] >>> TELEPORT EFFECT 4280 DEACTIVATED <<<"
                        };
                        println!("{}", tp_msg);
                        self.ws_client.send_debug_log(tp_msg);
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
