// Configuration module for FogRandoTracker

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tracing::{debug, error, info};
use windows::Win32::Foundation::HINSTANCE;
use windows::Win32::System::LibraryLoader::GetModuleFileNameW;

use crate::hotkey::Hotkey;

// =============================================================================
// CONFIGURATION STRUCTURES
// =============================================================================

/// Keyboard shortcuts configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyBindings {
    /// Key to toggle UI visibility
    #[serde(default = "default_toggle_ui")]
    pub toggle_ui: Hotkey,
    /// Key to toggle debug info display
    #[serde(default = "default_toggle_debug")]
    pub toggle_debug: Hotkey,
}

fn default_toggle_ui() -> Hotkey {
    Hotkey::from_name("f9").expect("f9 is a valid key")
}

fn default_toggle_debug() -> Hotkey {
    Hotkey::from_name("f10").expect("f10 is a valid key")
}

impl Default for KeyBindings {
    fn default() -> Self {
        Self {
            toggle_ui: default_toggle_ui(),
            toggle_debug: default_toggle_debug(),
        }
    }
}

/// Overlay display settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OverlaySettings {
    /// Path to TTF font file (relative to DLL or absolute)
    #[serde(default = "default_font_path")]
    pub font_path: String,

    /// Font size in pixels (16.0 recommended for 1080p, 24.0 for 4K)
    #[serde(default = "default_font_size")]
    pub font_size: f32,

    /// Background color as hex string "#RRGGBB"
    #[serde(default = "default_bg_color")]
    pub background_color: String,

    /// Background opacity (0.0 = transparent, 1.0 = opaque)
    #[serde(default = "default_bg_opacity")]
    pub background_opacity: f32,

    /// Main text color "#RRGGBB"
    #[serde(default = "default_text_color")]
    pub text_color: String,

    /// Disabled/secondary text color "#RRGGBB"
    #[serde(default = "default_text_disabled_color")]
    pub text_disabled_color: String,

    /// Discovered exit color "#RRGGBB"
    #[serde(default = "default_discovered_color")]
    pub discovered_color: String,

    /// Undiscovered exit color "#RRGGBB"
    #[serde(default = "default_undiscovered_color")]
    pub undiscovered_color: String,

    /// Show window border
    #[serde(default = "default_show_border")]
    pub show_border: bool,

    /// Border color "#RRGGBB" (only if show_border = true)
    #[serde(default = "default_border_color")]
    pub border_color: String,
}

fn default_font_path() -> String {
    String::new() // Empty = use system default (Segoe UI)
}
fn default_font_size() -> f32 {
    16.0
}
fn default_bg_color() -> String {
    "#141414".to_string()
}
fn default_bg_opacity() -> f32 {
    0.7
}
fn default_text_color() -> String {
    "#FFFFFF".to_string()
}
fn default_text_disabled_color() -> String {
    "#808080".to_string()
}
fn default_discovered_color() -> String {
    "#80FF80".to_string()
}
fn default_undiscovered_color() -> String {
    "#B3B3B3".to_string()
}
fn default_show_border() -> bool {
    false
}
fn default_border_color() -> String {
    "#404040".to_string()
}

impl Default for OverlaySettings {
    fn default() -> Self {
        Self {
            font_path: default_font_path(),
            font_size: default_font_size(),
            background_color: default_bg_color(),
            background_opacity: default_bg_opacity(),
            text_color: default_text_color(),
            text_disabled_color: default_text_disabled_color(),
            discovered_color: default_discovered_color(),
            undiscovered_color: default_undiscovered_color(),
            show_border: default_show_border(),
            border_color: default_border_color(),
        }
    }
}

/// Parse hex color "#RRGGBB" to [f32; 4] for ImGui
pub fn parse_hex_color(hex: &str, alpha: f32) -> [f32; 4] {
    let hex = hex.trim_start_matches('#');
    if hex.len() < 6 {
        return [1.0, 1.0, 1.0, alpha]; // Fallback to white
    }
    let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(255);
    let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(255);
    let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(255);
    [r as f32 / 255.0, g as f32 / 255.0, b as f32 / 255.0, alpha]
}

/// Server settings for fog-tracker integration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerSettings {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub mod_token: String,
    #[serde(default)]
    pub game_id: String,
    #[serde(default = "default_auto_reconnect")]
    pub auto_reconnect: bool,
}

fn default_auto_reconnect() -> bool {
    true
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            url: String::new(),
            mod_token: String::new(),
            game_id: String::new(),
            auto_reconnect: true,
        }
    }
}

/// Logging configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LoggingSettings {
    /// Enable debug console window for real-time logging
    #[serde(default)]
    pub console: bool,
    /// Log file path (relative to DLL directory or absolute). Empty = no file logging.
    #[serde(default)]
    pub log_file: String,
}

/// Main configuration structure
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Config {
    #[serde(default)]
    pub logging: LoggingSettings,
    #[serde(default)]
    pub keybindings: KeyBindings,
    #[serde(default)]
    pub overlay: OverlaySettings,
    #[serde(default)]
    pub server: ServerSettings,
}

// =============================================================================
// CONFIG LOADING
// =============================================================================

#[derive(Debug)]
pub enum ConfigError {
    PathError,
    ReadError(std::io::Error),
    ParseError(toml::de::Error),
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::PathError => write!(f, "Could not determine config file path"),
            ConfigError::ReadError(e) => write!(f, "Failed to read config file: {}", e),
            ConfigError::ParseError(e) => write!(f, "Failed to parse config file: {}", e),
        }
    }
}

/// Launcher config structure (stored in %APPDATA%/FogRandoTracker/launcher.toml)
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct LauncherConfig {
    #[serde(default)]
    server_url: String,
    #[serde(default)]
    mod_token: Option<String>,
    #[serde(default)]
    last_game_id: Option<String>,
}

impl Config {
    pub const CONFIG_FILENAME: &'static str = "fog_rando_tracker.toml";
    const LAUNCHER_CONFIG_DIR: &'static str = "FogRandoTracker";
    const LAUNCHER_CONFIG_FILENAME: &'static str = "launcher.toml";

    /// Get the DLL's directory path
    pub fn get_dll_directory(hmodule: HINSTANCE) -> Option<PathBuf> {
        let mut buffer = [0u16; 260];
        let len = unsafe { GetModuleFileNameW(hmodule, &mut buffer) } as usize;

        if len == 0 || len >= buffer.len() {
            return None;
        }

        let dll_path = String::from_utf16_lossy(&buffer[..len]);
        PathBuf::from(dll_path).parent().map(|p| p.to_path_buf())
    }

    /// Get the launcher config path (%APPDATA%/FogRandoTracker/launcher.toml)
    fn get_launcher_config_path() -> Option<PathBuf> {
        // Get %APPDATA% path using Windows API
        use windows::Win32::UI::Shell::{
            FOLDERID_RoamingAppData, SHGetKnownFolderPath, KF_FLAG_DEFAULT,
        };

        unsafe {
            let path_ptr =
                SHGetKnownFolderPath(&FOLDERID_RoamingAppData, KF_FLAG_DEFAULT, None).ok()?;
            let path_str = path_ptr.to_string().ok()?;
            windows::Win32::System::Com::CoTaskMemFree(Some(path_ptr.0 as *const _));
            let path = PathBuf::from(path_str)
                .join(Self::LAUNCHER_CONFIG_DIR)
                .join(Self::LAUNCHER_CONFIG_FILENAME);
            Some(path)
        }
    }

    /// Load launcher config and merge server settings
    fn load_launcher_config() -> Option<LauncherConfig> {
        let config_path = Self::get_launcher_config_path()?;

        if !config_path.exists() {
            debug!(
                path = %config_path.display(),
                "[config] No launcher config found"
            );
            return None;
        }

        match fs::read_to_string(&config_path) {
            Ok(contents) => match toml::from_str(&contents) {
                Ok(config) => {
                    info!(
                        path = %config_path.display(),
                        "[config] Loaded launcher config"
                    );
                    Some(config)
                }
                Err(e) => {
                    error!(error = %e, "[config] Failed to parse launcher config");
                    None
                }
            },
            Err(e) => {
                error!(error = %e, "[config] Failed to read launcher config");
                None
            }
        }
    }

    /// Load configuration from file next to the DLL, merging with launcher config
    pub fn load(hmodule: HINSTANCE) -> Result<Self, ConfigError> {
        let dir = Self::get_dll_directory(hmodule).ok_or(ConfigError::PathError)?;
        let config_path = dir.join(Self::CONFIG_FILENAME);

        debug!(
            path = %config_path.display(),
            "[config] Looking for local config"
        );

        // Load local config (overlay, keybindings)
        let mut config: Config = if config_path.exists() {
            let contents = fs::read_to_string(&config_path).map_err(ConfigError::ReadError)?;
            let config: Config = toml::from_str(&contents).map_err(ConfigError::ParseError)?;
            info!(
                path = %config_path.display(),
                "[config] Loaded local config"
            );
            config
        } else {
            debug!("[config] No local config found, using defaults");
            Config::default()
        };

        // Merge launcher config (server settings)
        if let Some(launcher_config) = Self::load_launcher_config() {
            // Override server settings from launcher config
            if !launcher_config.server_url.is_empty() {
                config.server.url = launcher_config.server_url;
                config.server.enabled = true;
            }
            if let Some(token) = launcher_config.mod_token {
                if !token.is_empty() {
                    config.server.mod_token = token;
                }
            }
            if let Some(game_id) = launcher_config.last_game_id {
                if !game_id.is_empty() {
                    config.server.game_id = game_id;
                }
            }
            debug!("[config] Merged launcher config into server settings");
        }

        Ok(config)
    }
}
