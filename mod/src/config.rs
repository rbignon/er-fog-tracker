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
}

fn default_toggle_ui() -> Hotkey {
    Hotkey::F9
}

impl Default for KeyBindings {
    fn default() -> Self {
        Self {
            toggle_ui: Hotkey::F9,
        }
    }
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
    #[serde(default)]
    pub keybindings: KeyBindings,
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

        hudhook::tracing::info!("Looking for config at: {}", config_path.display());

        if !config_path.exists() {
            return Err(ConfigError::FileNotFound(config_path));
        }

        let contents = fs::read_to_string(&config_path).map_err(ConfigError::ReadError)?;
        let config: Config = toml::from_str(&contents).map_err(ConfigError::ParseError)?;

        hudhook::tracing::info!("Loaded config from {}", config_path.display());
        Ok(config)
    }
}
