// API client for fog-tracker server communication

use serde::{Deserialize, Serialize};
use std::time::Duration;
use ureq::{Agent, AgentBuilder};

// =============================================================================
// Version Constants and Compatibility
// =============================================================================

/// Client version from Cargo.toml
pub const CLIENT_VERSION: &str = env!("CARGO_PKG_VERSION");

/// URL for downloading releases
pub const RELEASES_URL: &str = "https://github.com/rbignon/er-fog-tracker/releases";

/// Result of version compatibility check
#[derive(Debug, Clone, PartialEq)]
pub enum VersionCompatibility {
    /// Versions are compatible (same major, client >= server)
    Compatible,
    /// Update available (same major, client < server)
    UpdateAvailable { server_version: String },
    /// Client is too old (client major < server major)
    ClientTooOld { server_version: String },
    /// Server is too old (client major > server major)
    ServerTooOld { server_version: String },
}

impl VersionCompatibility {
    /// Check compatibility between client and server versions
    pub fn check(server_version: &str) -> Self {
        let client_major = CLIENT_VERSION
            .split('.')
            .next()
            .and_then(|s| s.parse::<u32>().ok())
            .unwrap_or(0);
        let server_major = server_version
            .split('.')
            .next()
            .and_then(|s| s.parse::<u32>().ok())
            .unwrap_or(0);

        if client_major < server_major {
            Self::ClientTooOld {
                server_version: server_version.to_string(),
            }
        } else if client_major > server_major {
            Self::ServerTooOld {
                server_version: server_version.to_string(),
            }
        } else if server_version > CLIENT_VERSION {
            Self::UpdateAvailable {
                server_version: server_version.to_string(),
            }
        } else {
            Self::Compatible
        }
    }

    /// Get the releases URL for downloading updates
    pub fn releases_url() -> &'static str {
        RELEASES_URL
    }

    /// Get the client version
    pub fn client_version() -> &'static str {
        CLIENT_VERSION
    }
}

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone)]
pub struct ApiClient {
    agent: Agent,
    base_url: String,
    token: String,
}

#[derive(Debug)]
pub enum ApiError {
    Network(String),
    Unauthorized,
    NotFound,
    RateLimited(String),
    BadRequest(String),
    ServerError(String),
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ApiError::Network(msg) => write!(f, "Network error: {}", msg),
            ApiError::Unauthorized => write!(f, "Invalid mod token"),
            ApiError::NotFound => write!(f, "Not found"),
            ApiError::RateLimited(msg) => write!(f, "Rate limited: {}", msg),
            ApiError::BadRequest(msg) => write!(f, "Bad request: {}", msg),
            ApiError::ServerError(msg) => write!(f, "Server error: {}", msg),
        }
    }
}

// =============================================================================
// API Response Types
// =============================================================================

#[derive(Debug, Clone, Deserialize)]
pub struct UserInfo {
    pub username: String,
    pub display_name: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)] // Fields from API, may be used later
pub struct GameSummary {
    pub id: String,
    pub seed: i64,
    pub label: Option<String>,
    pub discovery_count: i32,
    pub total_zones: i32,
    pub mod_connected: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GameListResponse {
    pub games: Vec<GameSummary>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GameCreateResponse {
    pub game_id: String,
    pub created: bool,
}

#[derive(Debug, Clone, Serialize)]
struct CreateGameRequest {
    spoiler_log: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    entity_mapping: Option<std::collections::HashMap<String, serde_json::Value>>,
}

#[derive(Debug, Clone, Deserialize)]
struct ErrorResponse {
    detail: String,
}

// =============================================================================
// API Client Implementation
// =============================================================================

/// Response with optional server version
pub struct ApiResponseWithVersion<T> {
    pub data: T,
    pub server_version: Option<String>,
}

impl ApiClient {
    pub fn new(base_url: &str, token: &str) -> Self {
        let user_agent = format!("FogRandoTracker-Launcher/{}", CLIENT_VERSION);
        let agent = AgentBuilder::new()
            .timeout(REQUEST_TIMEOUT)
            .user_agent(&user_agent)
            .build();

        // Normalize base URL (remove trailing slash)
        let base_url = base_url.trim_end_matches('/').to_string();

        Self {
            agent,
            base_url,
            token: token.to_string(),
        }
    }

    fn handle_response<T: for<'de> Deserialize<'de>>(
        response: Result<ureq::Response, ureq::Error>,
    ) -> Result<T, ApiError> {
        match response {
            Ok(resp) => resp
                .into_json()
                .map_err(|e| ApiError::Network(format!("Failed to parse response: {}", e))),
            Err(ureq::Error::Status(status, resp)) => {
                let detail = resp
                    .into_json::<ErrorResponse>()
                    .map(|e| e.detail)
                    .unwrap_or_else(|_| "Unknown error".to_string());

                match status {
                    401 => Err(ApiError::Unauthorized),
                    404 => Err(ApiError::NotFound),
                    429 => Err(ApiError::RateLimited(detail)),
                    400 => Err(ApiError::BadRequest(detail)),
                    _ => Err(ApiError::ServerError(detail)),
                }
            }
            Err(ureq::Error::Transport(e)) => Err(ApiError::Network(e.to_string())),
        }
    }

    fn handle_response_with_version<T: for<'de> Deserialize<'de>>(
        response: Result<ureq::Response, ureq::Error>,
    ) -> Result<ApiResponseWithVersion<T>, ApiError> {
        match response {
            Ok(resp) => {
                // Extract server version before consuming response
                let server_version = resp.header("Server-Version").map(|s| s.to_string());
                let data = resp
                    .into_json()
                    .map_err(|e| ApiError::Network(format!("Failed to parse response: {}", e)))?;
                Ok(ApiResponseWithVersion {
                    data,
                    server_version,
                })
            }
            Err(ureq::Error::Status(status, resp)) => {
                let detail = resp
                    .into_json::<ErrorResponse>()
                    .map(|e| e.detail)
                    .unwrap_or_else(|_| "Unknown error".to_string());

                match status {
                    401 => Err(ApiError::Unauthorized),
                    404 => Err(ApiError::NotFound),
                    429 => Err(ApiError::RateLimited(detail)),
                    400 => Err(ApiError::BadRequest(detail)),
                    _ => Err(ApiError::ServerError(detail)),
                }
            }
            Err(ureq::Error::Transport(e)) => Err(ApiError::Network(e.to_string())),
        }
    }

    /// Validate the mod token and get user info, also returns server version
    pub fn validate_token(&self) -> Result<ApiResponseWithVersion<UserInfo>, ApiError> {
        let url = format!("{}/api/mod/me", self.base_url);

        let response = self
            .agent
            .get(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Client-Version", CLIENT_VERSION)
            .call();

        Self::handle_response_with_version(response)
    }

    /// List user's games
    pub fn list_games(&self) -> Result<Vec<GameSummary>, ApiError> {
        let url = format!("{}/api/mod/games", self.base_url);

        let response = self
            .agent
            .get(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Client-Version", CLIENT_VERSION)
            .call();

        let list: GameListResponse = Self::handle_response(response)?;
        Ok(list.games)
    }

    /// Create a new game from spoiler log content
    pub fn create_game(
        &self,
        spoiler_log: &str,
        label: Option<&str>,
        entity_mapping: Option<std::collections::HashMap<String, serde_json::Value>>,
    ) -> Result<GameCreateResponse, ApiError> {
        let url = format!("{}/api/mod/games", self.base_url);

        let request = CreateGameRequest {
            spoiler_log: spoiler_log.to_string(),
            label: label.map(|s| s.to_string()),
            entity_mapping,
        };

        let response = self
            .agent
            .post(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Content-Type", "application/json")
            .set("Client-Version", CLIENT_VERSION)
            .send_json(&request);

        Self::handle_response(response)
    }

    /// Delete a game
    pub fn delete_game(&self, game_id: &str) -> Result<(), ApiError> {
        let url = format!("{}/api/mod/games/{}", self.base_url, game_id);

        let response = self
            .agent
            .delete(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Client-Version", CLIENT_VERSION)
            .call();

        match response {
            Ok(_) => Ok(()),
            Err(ureq::Error::Status(status, resp)) => {
                let detail = resp
                    .into_json::<ErrorResponse>()
                    .map(|e| e.detail)
                    .unwrap_or_else(|_| "Unknown error".to_string());

                match status {
                    401 => Err(ApiError::Unauthorized),
                    404 => Err(ApiError::NotFound),
                    429 => Err(ApiError::RateLimited(detail)),
                    400 => Err(ApiError::BadRequest(detail)),
                    _ => Err(ApiError::ServerError(detail)),
                }
            }
            Err(ureq::Error::Transport(e)) => Err(ApiError::Network(e.to_string())),
        }
    }
}

impl GameSummary {
    /// Format the game for display in the UI
    pub fn display_name(&self) -> String {
        self.label
            .clone()
            .unwrap_or_else(|| format!("Seed {}", self.seed))
    }

    /// Format progress as "X/Y zones"
    pub fn progress_text(&self) -> String {
        format!("{}/{} zones", self.discovery_count, self.total_zones)
    }

    /// Format relative time (simplified)
    #[allow(dead_code)]
    pub fn relative_time(&self) -> String {
        // Parse ISO timestamp and compute relative time
        // For simplicity, just show the date part
        if let Some(date) = self.updated_at.split('T').next() {
            date.to_string()
        } else {
            self.updated_at.clone()
        }
    }
}
