//! Version compatibility checking logic.
//!
//! This module provides cross-platform version comparison functionality
//! used by the launcher to check client-server compatibility.

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
        Self::check_versions(CLIENT_VERSION, server_version)
    }

    /// Check compatibility between two arbitrary versions (for testing)
    pub fn check_versions(client_version: &str, server_version: &str) -> Self {
        let client_major = client_version
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
        } else if server_version > client_version {
            Self::UpdateAvailable {
                server_version: server_version.to_string(),
            }
        } else {
            Self::Compatible
        }
    }

    /// Returns true if this is a blocking incompatibility
    pub fn is_blocking(&self) -> bool {
        matches!(self, Self::ClientTooOld { .. } | Self::ServerTooOld { .. })
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

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_compatible_same_version() {
        let result = VersionCompatibility::check_versions("0.1.0", "0.1.0");
        assert_eq!(result, VersionCompatibility::Compatible);
        assert!(!result.is_blocking());
    }

    #[test]
    fn test_version_compatible_client_newer() {
        // Client newer than server (same major) should be compatible
        let result = VersionCompatibility::check_versions("0.2.0", "0.1.0");
        assert_eq!(result, VersionCompatibility::Compatible);
        assert!(!result.is_blocking());
    }

    #[test]
    fn test_version_compatible_client_newer_patch() {
        let result = VersionCompatibility::check_versions("0.1.5", "0.1.0");
        assert_eq!(result, VersionCompatibility::Compatible);
        assert!(!result.is_blocking());
    }

    #[test]
    fn test_version_update_available_minor() {
        // Server has newer minor version
        let result = VersionCompatibility::check_versions("0.1.0", "0.2.0");
        assert!(matches!(
            result,
            VersionCompatibility::UpdateAvailable { .. }
        ));
        assert!(!result.is_blocking());

        if let VersionCompatibility::UpdateAvailable { server_version } = result {
            assert_eq!(server_version, "0.2.0");
        }
    }

    #[test]
    fn test_version_update_available_patch() {
        // Server has newer patch version
        let result = VersionCompatibility::check_versions("0.1.0", "0.1.1");
        assert!(matches!(
            result,
            VersionCompatibility::UpdateAvailable { .. }
        ));
        assert!(!result.is_blocking());

        if let VersionCompatibility::UpdateAvailable { server_version } = result {
            assert_eq!(server_version, "0.1.1");
        }
    }

    #[test]
    fn test_version_client_too_old() {
        // Server has higher major version - client needs update (blocking)
        let result = VersionCompatibility::check_versions("0.5.0", "1.0.0");
        assert!(matches!(result, VersionCompatibility::ClientTooOld { .. }));
        assert!(result.is_blocking());

        if let VersionCompatibility::ClientTooOld { server_version } = result {
            assert_eq!(server_version, "1.0.0");
        }
    }

    #[test]
    fn test_version_client_too_old_major_jump() {
        // Big major version jump
        let result = VersionCompatibility::check_versions("1.2.3", "3.0.0");
        assert!(matches!(result, VersionCompatibility::ClientTooOld { .. }));
        assert!(result.is_blocking());
    }

    #[test]
    fn test_version_server_too_old() {
        // Client has higher major version than server (blocking)
        let result = VersionCompatibility::check_versions("2.0.0", "1.5.0");
        assert!(matches!(result, VersionCompatibility::ServerTooOld { .. }));
        assert!(result.is_blocking());

        if let VersionCompatibility::ServerTooOld { server_version } = result {
            assert_eq!(server_version, "1.5.0");
        }
    }

    #[test]
    fn test_version_server_too_old_major_zero() {
        // Client at 1.x, server still at 0.x
        let result = VersionCompatibility::check_versions("1.0.0", "0.9.9");
        assert!(matches!(result, VersionCompatibility::ServerTooOld { .. }));
        assert!(result.is_blocking());
    }

    #[test]
    fn test_version_releases_url() {
        let url = VersionCompatibility::releases_url();
        assert!(url.contains("github.com"));
        assert!(url.contains("releases"));
    }

    #[test]
    fn test_version_client_version_format() {
        let version = VersionCompatibility::client_version();
        assert!(!version.is_empty());
        // Should be valid semver format
        let parts: Vec<&str> = version.split('.').collect();
        assert_eq!(parts.len(), 3, "Version should have 3 parts: {}", version);
        for part in parts {
            assert!(
                part.parse::<u32>().is_ok(),
                "Each part should be a number: {}",
                part
            );
        }
    }

    #[test]
    fn test_check_uses_client_version() {
        // check() should use CLIENT_VERSION
        let result = VersionCompatibility::check(CLIENT_VERSION);
        assert_eq!(result, VersionCompatibility::Compatible);
    }
}
