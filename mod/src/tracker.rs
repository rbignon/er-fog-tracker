// FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer

use std::path::PathBuf;
use std::time::{Duration, Instant};

use windows::Win32::Foundation::HINSTANCE;

use crate::config::Config;
use crate::game_state::{GameState, PlayerPosition};
use crate::websocket::{
    ConnectionStatus, DiscoveryStats, FogExit, IncomingMessage, WebSocketClient,
};

// =============================================================================
// FOG EVENTS
// =============================================================================

/// Pending fog event (entry recorded, waiting for exit)
#[derive(Clone, Debug)]
pub(crate) struct PendingFogEvent {
    entry: PlayerPosition,
}

// =============================================================================
// FOG RANDO TRACKER
// =============================================================================

/// Fog gate traversal tracking state
pub struct FogRandoTracker {
    game_state: GameState,
    pub(crate) was_in_fog: bool,
    pub(crate) pending_fog: Option<PendingFogEvent>,
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
    /// Directory where the DLL is located (for loading fonts, etc.)
    pub(crate) dll_dir: PathBuf,
    /// Font data loaded from file (must persist for imgui)
    pub(crate) font_data: Option<Vec<u8>>,
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
            was_in_fog: false,
            pending_fog: None,
            show_ui: true,
            show_debug: false,
            config,
            status_message: None,
            ws_client,
            current_zone: None,
            current_exits: Vec::new(),
            discovery_stats: None,
            last_map_id: None,
            dll_dir,
            font_data,
        })
    }

    /// Check for fog wall traversals each frame
    pub fn check_fog_traversal(&mut self) {
        // Detect map change (teleportation) - clear exits since we don't know exact zone
        if let Some(pos) = self.game_state.read_position() {
            if let Some(last_map) = self.last_map_id {
                if last_map != pos.map_id && !self.was_in_fog {
                    // Map changed without fog traversal = teleport
                    println!(
                        "[FOG] Map change detected (TP?): {} → {}, clearing exits",
                        crate::game_state::format_map_id(last_map),
                        pos.map_id_str
                    );
                    self.current_zone = None;
                    self.current_exits.clear();
                }
            }
            self.last_map_id = Some(pos.map_id);
        }

        let is_fog = self.game_state.is_in_fog_animation();

        // Detect fog entry: animation just started
        if is_fog && !self.was_in_fog {
            if let Some(pos) = self.game_state.read_position() {
                println!(
                    "[FOG] Entry detected [{}] pos=({:.1}, {:.1}, {:.1}) region={:?}",
                    pos.map_id_str, pos.x, pos.y, pos.z, pos.play_region_id
                );
                self.pending_fog = Some(PendingFogEvent { entry: pos });
            }
        }
        // Detect fog exit: we had a pending entry AND animation ended AND position is valid
        else if self.pending_fog.is_some() && !is_fog {
            if let Some(exit_pos) = self.game_state.read_position() {
                let pending = self.pending_fog.take().unwrap();
                let entry = &pending.entry;

                println!(
                    "[FOG] Exit detected [{}] pos=({:.1}, {:.1}, {:.1}) region={:?}",
                    exit_pos.map_id_str,
                    exit_pos.x,
                    exit_pos.y,
                    exit_pos.z,
                    exit_pos.play_region_id
                );
                println!(
                    "[FOG] Traversal complete: {} → {}",
                    entry.map_id_str, exit_pos.map_id_str
                );

                // Send discovery to server if connected
                if self.ws_client.is_connected() {
                    println!(
                        "[FOG] Sending to server: {} ({:.1}, {:.1}, {:.1}) region={:?} → {} ({:.1}, {:.1}, {:.1}) region={:?}",
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
                    println!("[FOG] Not connected to server, discovery not sent");
                }
            }
        }

        self.was_in_fog = is_fog;
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

    /// Load font data from file
    fn load_font_data(dll_dir: &PathBuf, font_path: &str) -> Option<Vec<u8>> {
        use std::fs;
        use std::path::Path;

        if font_path.is_empty() {
            return None;
        }

        let path = Path::new(font_path);
        let full_path = if path.is_absolute() {
            path.to_path_buf()
        } else {
            dll_dir.join(font_path)
        };

        if !full_path.exists() {
            eprintln!(
                "Font file not found: {}. Using default font.",
                full_path.display()
            );
            return None;
        }

        match fs::read(&full_path) {
            Ok(data) => {
                println!(
                    "Loaded font data from: {} ({} bytes)",
                    full_path.display(),
                    data.len()
                );
                Some(data)
            }
            Err(e) => {
                eprintln!("Failed to read font file {}: {}", full_path.display(), e);
                None
            }
        }
    }
}
