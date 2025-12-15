// Launcher configuration module
// Stored in %APPDATA%/FogRandoTracker/launcher.toml

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

const APP_NAME: &str = "FogRandoTracker";
const CONFIG_FILENAME: &str = "launcher.toml";
const DEFAULT_SERVER_URL: &str = "http://localhost:8001";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LauncherConfig {
    #[serde(default = "default_server_url")]
    pub server_url: String,

    #[serde(default)]
    pub mod_token: Option<String>,

    #[serde(default)]
    pub last_game_id: Option<String>,
}

fn default_server_url() -> String {
    DEFAULT_SERVER_URL.to_string()
}

impl Default for LauncherConfig {
    fn default() -> Self {
        Self {
            server_url: default_server_url(),
            mod_token: None,
            last_game_id: None,
        }
    }
}

impl LauncherConfig {
    /// Get the config directory path (%APPDATA%/FogRandoTracker/)
    pub fn config_dir() -> Option<PathBuf> {
        dirs::config_dir().map(|p| p.join(APP_NAME))
    }

    /// Get the full config file path
    pub fn config_path() -> Option<PathBuf> {
        Self::config_dir().map(|p| p.join(CONFIG_FILENAME))
    }

    /// Load configuration from file, or create default if not exists
    pub fn load() -> Self {
        let Some(config_path) = Self::config_path() else {
            eprintln!("[launcher] Could not determine config path, using defaults");
            return Self::default();
        };

        if !config_path.exists() {
            println!("[launcher] No config file found, using defaults");
            return Self::default();
        }

        match fs::read_to_string(&config_path) {
            Ok(contents) => match toml::from_str(&contents) {
                Ok(config) => {
                    println!("[launcher] Loaded config from {}", config_path.display());
                    config
                }
                Err(e) => {
                    eprintln!(
                        "[launcher] Failed to parse config {}: {}",
                        config_path.display(),
                        e
                    );
                    Self::default()
                }
            },
            Err(e) => {
                eprintln!(
                    "[launcher] Failed to read config {}: {}",
                    config_path.display(),
                    e
                );
                Self::default()
            }
        }
    }

    /// Save configuration to file
    pub fn save(&self) -> Result<(), String> {
        let config_dir = Self::config_dir().ok_or("Could not determine config directory")?;
        let config_path = Self::config_path().ok_or("Could not determine config path")?;

        // Create directory if it doesn't exist
        if !config_dir.exists() {
            fs::create_dir_all(&config_dir)
                .map_err(|e| format!("Failed to create config directory: {}", e))?;
        }

        let contents = toml::to_string_pretty(self)
            .map_err(|e| format!("Failed to serialize config: {}", e))?;

        fs::write(&config_path, contents)
            .map_err(|e| format!("Failed to write config file: {}", e))?;

        println!("[launcher] Saved config to {}", config_path.display());
        Ok(())
    }

    /// Check if we have a mod token configured
    pub fn has_token(&self) -> bool {
        self.mod_token
            .as_ref()
            .map(|t| !t.is_empty())
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = LauncherConfig::default();
        assert!(!config.has_token());
        assert!(config.last_game_id.is_none());
    }

    #[test]
    fn test_serialization() {
        let config = LauncherConfig {
            server_url: "https://example.com".to_string(),
            mod_token: Some("test_token".to_string()),
            last_game_id: Some("game123".to_string()),
        };

        let toml_str = toml::to_string(&config).unwrap();
        let parsed: LauncherConfig = toml::from_str(&toml_str).unwrap();

        assert_eq!(parsed.server_url, config.server_url);
        assert_eq!(parsed.mod_token, config.mod_token);
        assert_eq!(parsed.last_game_id, config.last_game_id);
    }
}
