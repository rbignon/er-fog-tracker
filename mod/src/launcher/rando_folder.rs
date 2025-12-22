//! Randomizer folder validation and processing.
//!
//! Validates that a folder contains the expected structure for a FogMod
//! randomized game and extracts the necessary data for game creation.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use super::emevd::{build_entity_mapping, EntityMapping};
use super::spoiler_validator::{validate_spoiler_content, SpoilerHeader, ValidationError};

// =============================================================================
// Error Types
// =============================================================================

#[derive(Debug, Clone)]
pub enum RandoFolderError {
    FolderNotFound,
    MissingEventDir,
    MissingSpoilerLogsDir,
    NoSpoilerLogFound,
    SpoilerValidation(ValidationError),
    EmevdParseFailed(String),
    ReadError(String),
}

impl std::fmt::Display for RandoFolderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RandoFolderError::FolderNotFound => write!(f, "Folder not found"),
            RandoFolderError::MissingEventDir => write!(f, "Missing 'event' directory"),
            RandoFolderError::MissingSpoilerLogsDir => {
                write!(f, "Missing 'spoiler_logs' directory")
            }
            RandoFolderError::NoSpoilerLogFound => write!(f, "No spoiler log found"),
            RandoFolderError::SpoilerValidation(e) => write!(f, "Spoiler validation: {}", e),
            RandoFolderError::EmevdParseFailed(msg) => write!(f, "EMEVD parsing: {}", msg),
            RandoFolderError::ReadError(msg) => write!(f, "Read error: {}", msg),
        }
    }
}

// =============================================================================
// Validated Folder Data
// =============================================================================

/// Result of validating a randomizer folder
#[derive(Debug, Clone)]
pub struct ValidatedRandoFolder {
    pub spoiler_path: PathBuf,
    pub event_path: PathBuf,
    pub header: SpoilerHeader,
}

/// Complete data extracted from a randomizer folder
#[derive(Debug)]
pub struct RandoFolderData {
    pub spoiler_content: String,
    pub entity_mapping: EntityMapping,
}

// =============================================================================
// Validation Functions
// =============================================================================

/// Validate a randomizer folder structure
pub fn validate_rando_folder(folder: &Path) -> Result<ValidatedRandoFolder, RandoFolderError> {
    if !folder.exists() || !folder.is_dir() {
        return Err(RandoFolderError::FolderNotFound);
    }

    // Check for event directory
    let event_path = folder.join("event");
    if !event_path.exists() || !event_path.is_dir() {
        return Err(RandoFolderError::MissingEventDir);
    }

    // Check for spoiler_logs directory
    let spoiler_logs_path = folder.join("spoiler_logs");
    if !spoiler_logs_path.exists() || !spoiler_logs_path.is_dir() {
        return Err(RandoFolderError::MissingSpoilerLogsDir);
    }

    // Find spoiler log file(s)
    let spoiler_files = find_spoiler_logs(&spoiler_logs_path)?;

    if spoiler_files.is_empty() {
        return Err(RandoFolderError::NoSpoilerLogFound);
    }

    // Pick the most recently modified spoiler log
    let spoiler_path = spoiler_files
        .into_iter()
        .max_by_key(|path| {
            fs::metadata(path)
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH)
        })
        .unwrap();

    // Validate spoiler content
    let content = fs::read_to_string(&spoiler_path)
        .map_err(|e| RandoFolderError::ReadError(e.to_string()))?;

    let header = validate_spoiler_content(&content).map_err(RandoFolderError::SpoilerValidation)?;

    Ok(ValidatedRandoFolder {
        spoiler_path,
        event_path,
        header,
    })
}

/// Find all .txt files in the spoiler_logs directory that look like spoiler logs
fn find_spoiler_logs(spoiler_logs_dir: &Path) -> Result<Vec<PathBuf>, RandoFolderError> {
    let entries =
        fs::read_dir(spoiler_logs_dir).map_err(|e| RandoFolderError::ReadError(e.to_string()))?;

    let mut spoiler_files = Vec::new();

    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() {
            if let Some(ext) = path.extension() {
                if ext == "txt" {
                    // Try to validate as spoiler log
                    if let Ok(content) = fs::read_to_string(&path) {
                        if validate_spoiler_content(&content).is_ok() {
                            spoiler_files.push(path);
                        }
                    }
                }
            }
        }
    }

    Ok(spoiler_files)
}

/// Extract full data from a validated randomizer folder
pub fn extract_rando_data(
    validated: &ValidatedRandoFolder,
) -> Result<RandoFolderData, RandoFolderError> {
    // Read spoiler content
    let spoiler_content = fs::read_to_string(&validated.spoiler_path)
        .map_err(|e| RandoFolderError::ReadError(e.to_string()))?;

    // Build entity mapping from EMEVD files
    let entity_mapping = build_entity_mapping(&validated.event_path)
        .map_err(|e| RandoFolderError::EmevdParseFailed(e.to_string()))?;

    Ok(RandoFolderData {
        spoiler_content,
        entity_mapping,
    })
}

/// Convert entity mapping to JSON-serializable format for API
pub fn entity_mapping_to_json(mapping: &EntityMapping) -> HashMap<String, serde_json::Value> {
    mapping
        .iter()
        .map(|(entity_id, info)| {
            let value = serde_json::json!({
                "source_map": info.source_map,
                "dest_map": info.dest_map,
                "source_entity": info.source_entity,
            });
            (entity_id.to_string(), value)
        })
        .collect()
}
