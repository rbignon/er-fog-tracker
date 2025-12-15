// API client for fog-vizu server communication

use serde::{Deserialize, Serialize};
use std::time::Duration;
use ureq::{Agent, AgentBuilder};

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
pub struct GameSummary {
    pub id: String,
    pub seed: i64,
    pub run_id: String,
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
}

#[derive(Debug, Clone, Deserialize)]
struct ErrorResponse {
    detail: String,
}

// =============================================================================
// API Client Implementation
// =============================================================================

impl ApiClient {
    pub fn new(base_url: &str, token: &str) -> Self {
        let agent = AgentBuilder::new()
            .timeout(REQUEST_TIMEOUT)
            .user_agent("FogRandoTracker-Launcher/1.0")
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

    /// Validate the mod token and get user info
    pub fn validate_token(&self) -> Result<UserInfo, ApiError> {
        let url = format!("{}/api/mod/me", self.base_url);

        let response = self
            .agent
            .get(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .call();

        Self::handle_response(response)
    }

    /// List user's games
    pub fn list_games(&self) -> Result<Vec<GameSummary>, ApiError> {
        let url = format!("{}/api/mod/games", self.base_url);

        let response = self
            .agent
            .get(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .call();

        let list: GameListResponse = Self::handle_response(response)?;
        Ok(list.games)
    }

    /// Create a new game from spoiler log content
    pub fn create_game(
        &self,
        spoiler_log: &str,
        label: Option<&str>,
    ) -> Result<GameCreateResponse, ApiError> {
        let url = format!("{}/api/mod/games", self.base_url);

        let request = CreateGameRequest {
            spoiler_log: spoiler_log.to_string(),
            label: label.map(|s| s.to_string()),
        };

        let response = self
            .agent
            .post(&url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Content-Type", "application/json")
            .send_json(&request);

        Self::handle_response(response)
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
