// FogRandoTracker - Fog gate traversal tracking for Fog Gate Randomizer

use std::time::{Duration, Instant};

use hudhook::tracing::{info, warn};
use libeldenring::pointers::Pointers;
use windows::Win32::Foundation::HINSTANCE;

use crate::config::Config;
use crate::websocket::{ConnectionStatus, IncomingMessage, WebSocketClient};
use crate::zone_names::{format_map_id, get_zone_name};

// =============================================================================
// FOG EVENTS
// =============================================================================

/// Pending fog event (entry recorded, waiting for exit)
#[derive(Clone, Debug)]
pub(crate) struct PendingFogEvent {
    entry_zone_name: String,
}

/// Animation ID for fog wall traversal
const FOG_WALL_ANIM_ID: u32 = 60060;

// =============================================================================
// FOG RANDO TRACKER
// =============================================================================

/// Fog gate traversal tracking state
pub struct FogRandoTracker {
    pub(crate) pointers: Pointers,
    pub(crate) fog_traversal_count: u32,
    pub(crate) last_anim: Option<u32>,
    pub(crate) pending_fog: Option<PendingFogEvent>,
    pub(crate) show_ui: bool,
    pub(crate) config: Config,
    pub(crate) status_message: Option<(String, Instant)>,
    pub(crate) ws_client: WebSocketClient,
}

impl FogRandoTracker {
    /// Create a new FogRandoTracker instance
    pub fn new(hmodule: HINSTANCE) -> Option<Self> {
        info!("Initializing FogRandoTracker...");

        // Load configuration - REQUIRED (from DLL directory)
        let config = match Config::load(hmodule) {
            Ok(cfg) => cfg,
            Err(e) => {
                hudhook::tracing::error!("Failed to load configuration: {}", e);
                hudhook::tracing::error!(
                    "Please ensure '{}' exists next to the DLL.",
                    Config::CONFIG_FILENAME
                );
                return None;
            }
        };

        info!(
            "Keybindings: Toggle UI={}",
            config.keybindings.toggle_ui.name()
        );

        let pointers = Pointers::new();

        // Wait for the game to be loaded
        let poll_interval = Duration::from_millis(100);
        loop {
            if let Some(menu_timer) = pointers.menu_timer.read() {
                if menu_timer > 0. {
                    break;
                }
            }
            std::thread::sleep(poll_interval);
        }

        info!("FogRandoTracker initialized!");

        // Initialize WebSocket client for server integration
        let mut ws_client = WebSocketClient::new(config.server.clone());
        if ws_client.is_enabled() {
            info!(
                "Server integration enabled, connecting to {}...",
                config.server.url
            );
            ws_client.connect();
        } else {
            info!("Server integration disabled (missing url, token, or game_id in config)");
        }

        Some(Self {
            pointers,
            fog_traversal_count: 0,
            last_anim: None,
            pending_fog: None,
            show_ui: true,
            config,
            status_message: None,
            ws_client,
        })
    }

    /// Check for fog wall traversals each frame
    pub fn check_fog_traversal(&mut self) {
        if let (Some([x, y, z, _, _]), Some(map_id)) = (
            self.pointers.global_position.read(),
            self.pointers.global_position.read_map_id(),
        ) {
            // Detect fog wall traversal
            let current_anim = self.pointers.cur_anim.read();
            let is_fog = current_anim.map(|a| a == FOG_WALL_ANIM_ID).unwrap_or(false);
            let was_fog = self
                .last_anim
                .map(|a| a == FOG_WALL_ANIM_ID)
                .unwrap_or(false);

            // Check if position data is valid (not during loading screen)
            let is_valid_position = map_id != 0xFFFFFFFF && (x != 0.0 || y != 0.0 || z != 0.0);

            if is_fog && !was_fog && is_valid_position {
                // Animation just started - record entry zone
                let entry_zone = get_zone_name(map_id);
                let map_id_str = format_map_id(map_id);
                info!(
                    "[FOG] Entry detected [{}] zone={} pos=({:.1}, {:.1}, {:.1})",
                    map_id_str, entry_zone, x, y, z
                );
                self.pending_fog = Some(PendingFogEvent {
                    entry_zone_name: entry_zone,
                });
            } else if self.pending_fog.is_some() && !is_fog && is_valid_position {
                // We had a pending fog entry AND animation is no longer fog AND position is valid
                if let Some(pending) = self.pending_fog.take() {
                    let exit_zone = get_zone_name(map_id);
                    let map_id_str = format_map_id(map_id);
                    info!(
                        "[FOG] Exit detected [{}] zone={} pos=({:.1}, {:.1}, {:.1})",
                        map_id_str, exit_zone, x, y, z
                    );
                    info!(
                        "[FOG] Traversal complete: {} → {}",
                        pending.entry_zone_name, exit_zone
                    );

                    // Send discovery to server if connected
                    if self.ws_client.is_connected() {
                        info!(
                            "[FOG] Sending to server: {} → {}",
                            pending.entry_zone_name, exit_zone
                        );
                        self.ws_client
                            .send_discovery(&pending.entry_zone_name, &exit_zone);
                    } else {
                        info!("[FOG] Not connected to server, discovery not sent");
                    }

                    self.fog_traversal_count += 1;
                }
            }
            self.last_anim = current_anim;
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

    /// Returns the player's current map_id and zone name
    pub fn get_current_position(&self) -> Option<(u32, String)> {
        if let Some(map_id) = self.pointers.global_position.read_map_id() {
            if map_id != 0xFFFFFFFF {
                return Some((map_id, get_zone_name(map_id)));
            }
        }
        None
    }

    /// Poll the WebSocket client for incoming messages
    pub fn poll_websocket(&mut self) {
        while let Some(msg) = self.ws_client.poll() {
            match msg {
                IncomingMessage::StatusChanged(status) => {
                    info!("WebSocket status: {:?}", status);
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
                IncomingMessage::DiscoveryAck { propagated } => {
                    info!(
                        "Discovery acknowledged by server ({} propagated)",
                        propagated.len()
                    );
                }
                IncomingMessage::Error(err) => {
                    warn!("WebSocket error: {}", err);
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
}
