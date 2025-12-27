// WebSocket client for fog-tracker server integration
//
// Handles connection to the server, authentication, and real-time
// transmission of fog gate discoveries.

use crossbeam_channel::{bounded, Receiver, Sender, TryRecvError};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use tracing::{debug, error, info, trace, warn};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{connect, Message, WebSocket};

use crate::core::map_utils::format_map_id;
use crate::core::protocol::{ServerMessage, ServerResponse};

// Re-export protocol types used by tracker.rs
pub use crate::core::protocol::{DiscoveryStats, FogExit, Position, PropagatedLink};

use super::config::ServerSettings;

// =============================================================================
// TYPES
// =============================================================================

/// Connection status for UI display
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionStatus {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error,
}

/// Messages sent to the WebSocket thread (internal channel)
#[derive(Debug)]
pub enum OutgoingMessage {
    /// Send a discovery event (with positions and play region IDs, server resolves zone names)
    DiscoveryV2 {
        source_map_id: u32,
        source_pos: Position,
        source_play_region_id: Option<u32>,
        target_map_id: u32,
        target_pos: Position,
        target_play_region_id: Option<u32>,
        /// Type of warp (fog, waygate, medal, coffin)
        warp_type: String,
        /// Destination entity ID (755890xxx for fog rando warps, enables direct lookup)
        destination_entity_id: u32,
    },
    /// Query current zone (after fast travel)
    ZoneQuery {
        map_id: u32,
        pos: Position,
        play_region_id: Option<u32>,
    },
    /// Respond to server ping
    Pong,
    /// Shutdown the connection
    Shutdown,
}

/// Messages received from the WebSocket thread (internal channel)
#[derive(Debug)]
pub enum IncomingMessage {
    /// Connection status changed
    StatusChanged(ConnectionStatus),
    /// Discovery acknowledged by server
    DiscoveryAck {
        propagated: Vec<PropagatedLink>,
        current_zone: Option<String>,
        exits: Vec<FogExit>,
        stats: DiscoveryStats,
    },
    /// Zone query response (after fast travel)
    ZoneQueryAck {
        zone: Option<String>,
        exits: Vec<FogExit>,
    },
    /// Error message
    Error(String),
    /// Server sent a ping
    Ping,
}

// =============================================================================
// WEBSOCKET CLIENT
// =============================================================================

/// Thread-safe WebSocket client for server communication
pub struct WebSocketClient {
    /// Settings from config
    settings: ServerSettings,
    /// Channel to send messages to the WebSocket thread
    tx: Option<Sender<OutgoingMessage>>,
    /// Channel to receive messages from the WebSocket thread
    rx: Option<Receiver<IncomingMessage>>,
    /// Handle to the WebSocket thread
    thread_handle: Option<JoinHandle<()>>,
    /// Flag to signal shutdown
    shutdown_flag: Arc<AtomicBool>,
    /// Current connection status (cached for UI)
    current_status: ConnectionStatus,
    /// Last error message
    last_error: Option<String>,
}

impl WebSocketClient {
    /// Create a new WebSocket client (does not connect yet)
    pub fn new(settings: ServerSettings) -> Self {
        Self {
            settings,
            tx: None,
            rx: None,
            thread_handle: None,
            shutdown_flag: Arc::new(AtomicBool::new(false)),
            current_status: ConnectionStatus::Disconnected,
            last_error: None,
        }
    }

    /// Check if server integration is enabled
    pub fn is_enabled(&self) -> bool {
        self.settings.enabled
            && !self.settings.url.is_empty()
            && !self.settings.mod_token.is_empty()
            && !self.settings.game_id.is_empty()
    }

    /// Start the WebSocket connection in a background thread
    pub fn connect(&mut self) {
        if !self.is_enabled() {
            warn!("[WS] Client not enabled or missing config");
            return;
        }

        if self.thread_handle.is_some() {
            warn!("[WS] Client already running");
            return;
        }

        // Create channels (128 capacity to handle bursts without dropping messages)
        let (outgoing_tx, outgoing_rx) = bounded::<OutgoingMessage>(128);
        let (incoming_tx, incoming_rx) = bounded::<IncomingMessage>(128);

        self.tx = Some(outgoing_tx);
        self.rx = Some(incoming_rx);

        // Reset shutdown flag
        self.shutdown_flag.store(false, Ordering::SeqCst);
        let shutdown_flag = Arc::clone(&self.shutdown_flag);

        // Clone settings for the thread
        let settings = self.settings.clone();

        // Spawn the WebSocket thread
        let handle = thread::spawn(move || {
            websocket_thread(settings, outgoing_rx, incoming_tx, shutdown_flag);
        });

        self.thread_handle = Some(handle);
        self.current_status = ConnectionStatus::Connecting;
    }

    /// Disconnect from the server
    pub fn disconnect(&mut self) {
        self.shutdown_flag.store(true, Ordering::SeqCst);

        // Send shutdown message
        if let Some(tx) = &self.tx {
            let _ = tx.send(OutgoingMessage::Shutdown);
        }

        // Wait for thread to finish
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }

        self.tx = None;
        self.rx = None;
        self.current_status = ConnectionStatus::Disconnected;
    }

    /// Send a discovery event to the server (with positions and play region IDs, server resolves zone names)
    pub fn send_discovery_v2(
        &self,
        source_map_id: u32,
        source_pos: (f32, f32, f32),
        source_play_region_id: Option<u32>,
        target_map_id: u32,
        target_pos: (f32, f32, f32),
        target_play_region_id: Option<u32>,
        warp_type: &str,
        destination_entity_id: u32,
    ) {
        if let Some(tx) = &self.tx {
            let _ = tx.try_send(OutgoingMessage::DiscoveryV2 {
                source_map_id,
                source_pos: Position {
                    x: source_pos.0,
                    y: source_pos.1,
                    z: source_pos.2,
                },
                source_play_region_id,
                target_map_id,
                target_pos: Position {
                    x: target_pos.0,
                    y: target_pos.1,
                    z: target_pos.2,
                },
                target_play_region_id,
                warp_type: warp_type.to_string(),
                destination_entity_id,
            });
        }
    }

    /// Send a zone query to the server (after fast travel)
    pub fn send_zone_query(&self, map_id: u32, pos: (f32, f32, f32), play_region_id: Option<u32>) {
        if let Some(tx) = &self.tx {
            let _ = tx.try_send(OutgoingMessage::ZoneQuery {
                map_id,
                pos: Position {
                    x: pos.0,
                    y: pos.1,
                    z: pos.2,
                },
                play_region_id,
            });
        }
    }

    /// Poll for incoming messages (call this in the main loop)
    pub fn poll(&mut self) -> Option<IncomingMessage> {
        let rx = self.rx.as_ref()?;

        match rx.try_recv() {
            Ok(msg) => {
                // Update cached status
                if let IncomingMessage::StatusChanged(status) = &msg {
                    self.current_status = *status;
                }
                if let IncomingMessage::Error(err) = &msg {
                    self.last_error = Some(err.clone());
                }
                if let IncomingMessage::Ping = &msg {
                    // Auto-respond to pings
                    if let Some(tx) = &self.tx {
                        let _ = tx.try_send(OutgoingMessage::Pong);
                    }
                }
                Some(msg)
            }
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => {
                self.current_status = ConnectionStatus::Disconnected;
                None
            }
        }
    }

    /// Get current connection status
    pub fn status(&self) -> ConnectionStatus {
        self.current_status
    }

    /// Get last error message
    pub fn last_error(&self) -> Option<&str> {
        self.last_error.as_deref()
    }

    /// Check if connected
    pub fn is_connected(&self) -> bool {
        self.current_status == ConnectionStatus::Connected
    }
}

impl Drop for WebSocketClient {
    fn drop(&mut self) {
        self.disconnect();
    }
}

// =============================================================================
// WEBSOCKET THREAD
// =============================================================================

/// Main WebSocket thread function
fn websocket_thread(
    settings: ServerSettings,
    outgoing_rx: Receiver<OutgoingMessage>,
    incoming_tx: Sender<IncomingMessage>,
    shutdown_flag: Arc<AtomicBool>,
) {
    let mut reconnect_delay = Duration::from_secs(1);
    let max_reconnect_delay = Duration::from_secs(30);

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            break;
        }

        // Build WebSocket URL (convert http(s) to ws(s))
        let base_url = settings.url.trim_end_matches('/');
        let ws_base = if base_url.starts_with("https://") {
            base_url.replacen("https://", "wss://", 1)
        } else if base_url.starts_with("http://") {
            base_url.replacen("http://", "ws://", 1)
        } else {
            base_url.to_string()
        };
        let ws_url = format!("{}/ws/mod/{}", ws_base, settings.game_id);

        info!(url = %ws_url, "[WS] Connecting...");
        let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connecting));

        match connect_and_authenticate(&ws_url, &settings.mod_token) {
            Ok((mut socket, initial_stats)) => {
                info!("[WS] Connected and authenticated");
                let _ =
                    incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connected));
                reconnect_delay = Duration::from_secs(1); // Reset on successful connect

                // Send initial stats if provided by server
                if let Some(stats) = initial_stats {
                    debug!(
                        discovered = stats.discovered,
                        total = stats.total,
                        "[WS] Initial stats from auth_ok"
                    );
                    let _ = incoming_tx.send(IncomingMessage::DiscoveryAck {
                        propagated: vec![],
                        current_zone: None,
                        exits: vec![],
                        stats,
                    });
                }

                // Main message loop
                let result = message_loop(&mut socket, &outgoing_rx, &incoming_tx, &shutdown_flag);

                if let Err(ref e) = result {
                    info!(error = %e, "[WS] Message loop ended");
                }

                // Close socket gracefully
                let _ = socket.close(None);

                if result.is_err()
                    && settings.auto_reconnect
                    && !shutdown_flag.load(Ordering::SeqCst)
                {
                    let _ = incoming_tx.send(IncomingMessage::StatusChanged(
                        ConnectionStatus::Reconnecting,
                    ));
                }
            }
            Err(e) => {
                error!(error = %e, "[WS] Connection failed");
                let _ = incoming_tx.send(IncomingMessage::Error(e.clone()));
                let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Error));

                if !settings.auto_reconnect {
                    break;
                }
            }
        }

        // Check if we should reconnect
        if !settings.auto_reconnect || shutdown_flag.load(Ordering::SeqCst) {
            break;
        }

        // Wait before reconnecting
        info!(
            delay_secs = reconnect_delay.as_secs(),
            "[WS] Reconnecting..."
        );
        thread::sleep(reconnect_delay);

        // Exponential backoff
        reconnect_delay = (reconnect_delay * 2).min(max_reconnect_delay);
    }

    let _ = incoming_tx.send(IncomingMessage::StatusChanged(
        ConnectionStatus::Disconnected,
    ));
}

/// Connect to the WebSocket server and authenticate
///
/// Returns the socket and optional initial stats from auth_ok.
fn connect_and_authenticate(
    url: &str,
    api_token: &str,
) -> Result<(WebSocket<MaybeTlsStream<TcpStream>>, Option<DiscoveryStats>), String> {
    // tungstenite handles TLS automatically for wss:// URLs
    debug!(url, "[WS] Opening socket");
    let (mut socket, _response) = connect(url).map_err(|e| format!("Connection failed: {}", e))?;

    // Send auth message
    debug!("[WS] Socket opened, sending auth...");
    let auth_msg = ServerMessage::Auth {
        token: api_token.to_string(),
    };
    let auth_json = serde_json::to_string(&auth_msg).map_err(|e| format!("JSON error: {}", e))?;
    socket
        .send(Message::Text(auth_json))
        .map_err(|e| format!("Send error: {}", e))?;

    // Wait for auth response (with timeout via socket read timeout)
    debug!("[WS] Waiting for auth response...");
    let response = socket.read().map_err(|e| format!("Read error: {}", e))?;

    match response {
        Message::Text(text) => {
            debug!(response = %text, "[WS] Auth response received");
            let resp: ServerResponse =
                serde_json::from_str(&text).map_err(|e| format!("JSON parse error: {}", e))?;

            match resp {
                ServerResponse::AuthOk { stats } => {
                    info!("[WS] Auth successful");
                    Ok((socket, stats))
                }
                ServerResponse::AuthError { message } => {
                    error!(message = %message, "[WS] Auth failed");
                    Err(format!("Auth failed: {}", message))
                }
                other => Err(format!("Unexpected response during auth: {:?}", other)),
            }
        }
        other => Err(format!("Unexpected message type during auth: {:?}", other)),
    }
}

/// Main message loop for an established connection
fn message_loop(
    socket: &mut WebSocket<MaybeTlsStream<TcpStream>>,
    outgoing_rx: &Receiver<OutgoingMessage>,
    incoming_tx: &Sender<IncomingMessage>,
    shutdown_flag: &Arc<AtomicBool>,
) -> Result<(), String> {
    // Set socket to non-blocking for polling
    // Note: For TLS streams, we access the underlying TCP socket
    match socket.get_ref() {
        MaybeTlsStream::Plain(tcp) => {
            let _ = tcp.set_nonblocking(true);
        }
        MaybeTlsStream::NativeTls(tls_stream) => {
            let _ = tls_stream.get_ref().set_nonblocking(true);
        }
        _ => {
            // Other TLS backends not currently supported
        }
    }

    let mut last_ping_response = Instant::now();
    let ping_timeout = Duration::from_secs(60);

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            return Ok(());
        }

        // Check for outgoing messages
        match outgoing_rx.try_recv() {
            Ok(OutgoingMessage::DiscoveryV2 {
                source_map_id,
                ref source_pos,
                source_play_region_id,
                target_map_id,
                ref target_pos,
                target_play_region_id,
                ref warp_type,
                destination_entity_id,
            }) => {
                let source_map_str = format_map_id(source_map_id);
                let target_map_str = format_map_id(target_map_id);
                debug!(
                    source = %source_map_str,
                    source_pos = format!("({:.1}, {:.1}, {:.1})", source_pos.x, source_pos.y, source_pos.z),
                    source_region = ?source_play_region_id,
                    target = %target_map_str,
                    target_pos = format!("({:.1}, {:.1}, {:.1})", target_pos.x, target_pos.y, target_pos.z),
                    target_region = ?target_play_region_id,
                    warp_type,
                    dest_entity = destination_entity_id,
                    "[WS TX] Discovery v2"
                );
                let msg = ServerMessage::DiscoveryV2 {
                    source_map_id: source_map_str,
                    source_pos: source_pos.clone(),
                    source_play_region_id,
                    target_map_id: target_map_str,
                    target_pos: target_pos.clone(),
                    target_play_region_id,
                    warp_type: warp_type.clone(),
                    destination_entity_id,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::ZoneQuery {
                map_id,
                ref pos,
                play_region_id,
            }) => {
                let map_str = format_map_id(map_id);
                debug!(
                    map_id = %map_str,
                    pos = format!("({:.1}, {:.1}, {:.1})", pos.x, pos.y, pos.z),
                    play_region_id = ?play_region_id,
                    "[WS TX] ZoneQuery"
                );
                let msg = ServerMessage::ZoneQuery {
                    map_id: map_str,
                    pos: pos.clone(),
                    play_region_id,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::Pong) => {
                let msg = ServerMessage::Pong;
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
                last_ping_response = Instant::now();
            }
            Ok(OutgoingMessage::Shutdown) => {
                debug!("[WS TX] Shutdown");
                return Ok(());
            }
            Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => {
                return Err("Outgoing channel disconnected".to_string());
            }
        }

        // Check for incoming messages (non-blocking)
        match socket.read() {
            Ok(Message::Text(text)) => {
                trace!(raw = %text, "[WS RX]");
                match serde_json::from_str::<ServerResponse>(&text) {
                    Ok(resp) => match resp {
                        ServerResponse::Ping => {
                            let _ = incoming_tx.send(IncomingMessage::Ping);
                        }
                        ServerResponse::DiscoveryV2Ack {
                            ref propagated,
                            ref current_zone,
                            ref exits,
                            ref stats,
                        } => {
                            debug!(
                                zone = current_zone.as_deref().unwrap_or("?"),
                                propagated = propagated.len(),
                                exits = exits.len(),
                                discovered = stats.discovered,
                                total = stats.total,
                                "[WS RX] DiscoveryV2Ack"
                            );
                            let _ = incoming_tx.send(IncomingMessage::DiscoveryAck {
                                propagated: propagated.clone(),
                                current_zone: current_zone.clone(),
                                exits: exits.clone(),
                                stats: stats.clone(),
                            });
                        }
                        ServerResponse::Discovery {
                            ref propagated,
                            ref stats,
                        } => {
                            // Web UI discovery broadcast - just update stats
                            debug!(
                                propagated = propagated.len(),
                                discovered = stats.discovered,
                                total = stats.total,
                                "[WS RX] Discovery (from web)"
                            );
                            // Send as DiscoveryAck without zone/exits (only stats matter)
                            let _ = incoming_tx.send(IncomingMessage::DiscoveryAck {
                                propagated: propagated.clone(),
                                current_zone: None,
                                exits: vec![],
                                stats: stats.clone(),
                            });
                        }
                        ServerResponse::ZoneQueryAck {
                            ref zone,
                            ref exits,
                        } => {
                            debug!(
                                zone = zone.as_deref().unwrap_or("?"),
                                exits = exits.len(),
                                "[WS RX] ZoneQueryAck"
                            );
                            let _ = incoming_tx.send(IncomingMessage::ZoneQueryAck {
                                zone: zone.clone(),
                                exits: exits.clone(),
                            });
                        }
                        ServerResponse::Error { ref message } => {
                            error!(message, "[WS RX] Error");
                            let _ = incoming_tx.send(IncomingMessage::Error(message.clone()));
                        }
                        _ => {
                            debug!(response = ?resp, "[WS RX] Other");
                        }
                    },
                    Err(e) => {
                        warn!(
                            error = %e,
                            raw = %text,
                            "[WS RX] Failed to parse server response"
                        );
                    }
                }
            }
            Ok(Message::Close(_)) => {
                return Err("Server closed connection".to_string());
            }
            Err(tungstenite::Error::Io(ref e)) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No data available, continue
            }
            Err(e) => {
                return Err(format!("Read error: {}", e));
            }
            _ => {}
        }

        // Check for ping timeout
        if last_ping_response.elapsed() > ping_timeout {
            return Err("Ping timeout".to_string());
        }

        // Small sleep to avoid busy-waiting
        thread::sleep(Duration::from_millis(10));
    }
}
