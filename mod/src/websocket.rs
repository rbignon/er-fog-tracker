// WebSocket client for fog-vizu server integration
//
// Handles connection to the server, authentication, and real-time
// transmission of fog gate discoveries.

use crossbeam_channel::{bounded, Receiver, Sender, TryRecvError};
use serde::{Deserialize, Serialize};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{connect, Message, WebSocket};

use crate::config::ServerSettings;
use crate::zone_names::format_map_id;

// =============================================================================
// TYPES
// =============================================================================

/// Connection status for UI display
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionStatus {
    Disconnected,
    Connecting,
    #[allow(dead_code)]
    Authenticating,
    Connected,
    Reconnecting,
    Error,
}

impl ConnectionStatus {
    pub fn display_text(&self) -> &'static str {
        match self {
            ConnectionStatus::Disconnected => "Disconnected",
            ConnectionStatus::Connecting => "Connecting...",
            ConnectionStatus::Authenticating => "Authenticating...",
            ConnectionStatus::Connected => "Connected",
            ConnectionStatus::Reconnecting => "Reconnecting...",
            ConnectionStatus::Error => "Error",
        }
    }

    pub fn display_color(&self) -> [f32; 4] {
        match self {
            ConnectionStatus::Disconnected => [0.5, 0.5, 0.5, 1.0], // Gray
            ConnectionStatus::Connecting => [1.0, 1.0, 0.0, 1.0],   // Yellow
            ConnectionStatus::Authenticating => [1.0, 0.8, 0.0, 1.0], // Orange
            ConnectionStatus::Connected => [0.0, 1.0, 0.0, 1.0],    // Green
            ConnectionStatus::Reconnecting => [1.0, 0.5, 0.0, 1.0], // Orange
            ConnectionStatus::Error => [1.0, 0.0, 0.0, 1.0],        // Red
        }
    }
}

/// Messages sent to the WebSocket thread
#[derive(Debug)]
pub enum OutgoingMessage {
    /// Send a discovery event
    Discovery {
        source: String,
        source_map_id: u32,
        target: String,
        target_map_id: u32,
    },
    /// Respond to server ping
    Pong,
    /// Shutdown the connection
    Shutdown,
}

/// Messages received from the WebSocket thread
#[derive(Debug)]
pub enum IncomingMessage {
    /// Connection status changed
    StatusChanged(ConnectionStatus),
    /// Discovery acknowledged by server
    DiscoveryAck { propagated: Vec<PropagatedLink> },
    /// Error message
    Error(String),
    /// Server sent a ping
    Ping,
}

/// A propagated link from the server response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PropagatedLink {
    pub source: String,
    pub target: String,
}

// =============================================================================
// PROTOCOL MESSAGES
// =============================================================================

/// Messages sent to the server
#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum ServerMessage {
    Auth { token: String },
    Discovery {
        source: String,
        source_map_id: String,
        target: String,
        target_map_id: String,
    },
    Pong,
}

/// Messages received from the server
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum ServerResponse {
    AuthOk,
    AuthError { message: String },
    DiscoveryAck { propagated: Vec<PropagatedLink> },
    Ping,
    Error { message: String },
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
            eprintln!("WebSocket client not enabled or missing config");
            return;
        }

        if self.thread_handle.is_some() {
            eprintln!("WebSocket client already running");
            return;
        }

        // Create channels
        let (outgoing_tx, outgoing_rx) = bounded::<OutgoingMessage>(32);
        let (incoming_tx, incoming_rx) = bounded::<IncomingMessage>(32);

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

    /// Send a discovery event to the server
    pub fn send_discovery(&self, source: &str, source_map_id: u32, target: &str, target_map_id: u32) {
        if let Some(tx) = &self.tx {
            let _ = tx.try_send(OutgoingMessage::Discovery {
                source: source.to_string(),
                source_map_id,
                target: target.to_string(),
                target_map_id,
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

        // Build WebSocket URL
        let ws_url = format!(
            "{}/ws/mod/{}",
            settings.url.trim_end_matches('/'),
            settings.game_id
        );

        println!("[WS] Connecting to {}...", ws_url);
        let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connecting));

        match connect_and_authenticate(&ws_url, &settings.mod_token) {
            Ok(mut socket) => {
                println!("[WS] Connected and authenticated");
                let _ =
                    incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connected));
                reconnect_delay = Duration::from_secs(1); // Reset on successful connect

                // Main message loop
                let result = message_loop(&mut socket, &outgoing_rx, &incoming_tx, &shutdown_flag);

                if let Err(ref e) = result {
                    println!("[WS] Message loop ended: {}", e);
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
                eprintln!("WebSocket connection failed: {}", e);
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
        println!("Reconnecting in {} seconds...", reconnect_delay.as_secs());
        thread::sleep(reconnect_delay);

        // Exponential backoff
        reconnect_delay = (reconnect_delay * 2).min(max_reconnect_delay);
    }

    let _ = incoming_tx.send(IncomingMessage::StatusChanged(
        ConnectionStatus::Disconnected,
    ));
}

/// Connect to the WebSocket server and authenticate
fn connect_and_authenticate(
    url: &str,
    api_token: &str,
) -> Result<WebSocket<MaybeTlsStream<TcpStream>>, String> {
    // tungstenite handles TLS automatically for wss:// URLs
    println!("[WS] Opening socket to {}", url);
    let (mut socket, _response) =
        connect(url).map_err(|e| format!("Connection failed: {}", e))?;

    // Send auth message
    println!("[WS] Socket opened, sending auth...");
    let auth_msg = ServerMessage::Auth {
        token: api_token.to_string(),
    };
    let auth_json = serde_json::to_string(&auth_msg).map_err(|e| format!("JSON error: {}", e))?;
    socket
        .send(Message::Text(auth_json))
        .map_err(|e| format!("Send error: {}", e))?;

    // Wait for auth response (with timeout via socket read timeout)
    println!("[WS] Waiting for auth response...");
    let response = socket.read().map_err(|e| format!("Read error: {}", e))?;

    match response {
        Message::Text(text) => {
            println!("[WS] Auth response: {}", text);
            let resp: ServerResponse =
                serde_json::from_str(&text).map_err(|e| format!("JSON parse error: {}", e))?;

            match resp {
                ServerResponse::AuthOk => {
                    println!("[WS] Auth successful");
                    Ok(socket)
                }
                ServerResponse::AuthError { message } => {
                    println!("[WS] Auth failed: {}", message);
                    Err(format!("Auth failed: {}", message))
                }
                _ => Err("Unexpected response during auth".to_string()),
            }
        }
        _ => Err("Unexpected message type during auth".to_string()),
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
    if let MaybeTlsStream::Plain(ref tcp) = socket.get_ref() {
        let _ = tcp.set_nonblocking(true);
    }

    let mut last_ping_response = Instant::now();
    let ping_timeout = Duration::from_secs(60);

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            return Ok(());
        }

        // Check for outgoing messages
        match outgoing_rx.try_recv() {
            Ok(OutgoingMessage::Discovery {
                ref source,
                source_map_id,
                ref target,
                target_map_id,
            }) => {
                let source_map_str = format_map_id(source_map_id);
                let target_map_str = format_map_id(target_map_id);
                println!(
                    "[WS TX] Discovery: {} [{}] → {} [{}]",
                    source, source_map_str, target, target_map_str
                );
                let msg = ServerMessage::Discovery {
                    source: source.clone(),
                    source_map_id: source_map_str,
                    target: target.clone(),
                    target_map_id: target_map_str,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::Pong) => {
                println!("[WS TX] Pong");
                let msg = ServerMessage::Pong;
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
                last_ping_response = Instant::now();
            }
            Ok(OutgoingMessage::Shutdown) => {
                println!("[WS TX] Shutdown");
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
                println!("[WS RX] Raw: {}", text);
                if let Ok(resp) = serde_json::from_str::<ServerResponse>(&text) {
                    match resp {
                        ServerResponse::Ping => {
                            println!("[WS RX] Ping");
                            let _ = incoming_tx.send(IncomingMessage::Ping);
                        }
                        ServerResponse::DiscoveryAck { ref propagated } => {
                            println!(
                                "[WS RX] DiscoveryAck (propagated: {})",
                                propagated.len()
                            );
                            let _ = incoming_tx
                                .send(IncomingMessage::DiscoveryAck { propagated: propagated.clone() });
                        }
                        ServerResponse::Error { ref message } => {
                            println!("[WS RX] Error: {}", message);
                            let _ = incoming_tx.send(IncomingMessage::Error(message.clone()));
                        }
                        _ => {
                            println!("[WS RX] Other: {:?}", resp);
                        }
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
