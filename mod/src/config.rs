// Configuration module for FogRandoTracker

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
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

    /// Font size in pixels
    #[serde(default = "default_font_size")]
    pub font_size: f32,

    /// Font scale factor (1.0 = default, 1.5 = 150%, etc.)
    #[serde(default = "default_font_scale")]
    pub font_scale: f32,

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
fn default_font_scale() -> f32 {
    1.0
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
            font_scale: default_font_scale(),
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

/// Server settings for fog-vizu integration
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

/// Main configuration structure
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Config {
    /// Enable debug console window for real-time logging
    #[serde(default)]
    pub debug_console: bool,
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
    FileNotFound(PathBuf),
    ReadError(std::io::Error),
    ParseError(toml::de::Error),
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::PathError => write!(f, "Could not determine config file path"),
            ConfigError::FileNotFound(path) => {
                write!(f, "Config file not found: {}", path.display())
            }
            ConfigError::ReadError(e) => write!(f, "Failed to read config file: {}", e),
            ConfigError::ParseError(e) => write!(f, "Failed to parse config file: {}", e),
        }
    }
}

impl Config {
    pub const CONFIG_FILENAME: &'static str = "fog_rando_tracker.toml";

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

    /// Load configuration from file next to the DLL
    pub fn load(hmodule: HINSTANCE) -> Result<Self, ConfigError> {
        let dir = Self::get_dll_directory(hmodule).ok_or(ConfigError::PathError)?;
        let config_path = dir.join(Self::CONFIG_FILENAME);

        println!("Looking for config at: {}", config_path.display());

        if !config_path.exists() {
            return Err(ConfigError::FileNotFound(config_path));
        }

        let contents = fs::read_to_string(&config_path).map_err(ConfigError::ReadError)?;
        let config: Config = toml::from_str(&contents).map_err(ConfigError::ParseError)?;

        println!("Loaded config from {}", config_path.display());
        Ok(config)
    }
}
