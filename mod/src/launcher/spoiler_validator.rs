// Spoiler log header validation
// Quick validation without full parsing (parsing is done server-side)

use std::fs;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct SpoilerHeader {
    pub seed: u64,
    pub options_line: String,
}

#[derive(Debug, Clone)]
pub enum ValidationError {
    FileNotFound,
    ReadError(String),
    InvalidFormat(String),
    NoSeedFound,
}

impl std::fmt::Display for ValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ValidationError::FileNotFound => write!(f, "File not found"),
            ValidationError::ReadError(msg) => write!(f, "Failed to read file: {}", msg),
            ValidationError::InvalidFormat(msg) => write!(f, "Invalid format: {}", msg),
            ValidationError::NoSeedFound => write!(f, "No seed found in spoiler log header"),
        }
    }
}

/// Validate a spoiler log file and extract header info
pub fn validate_spoiler_file(path: &Path) -> Result<SpoilerHeader, ValidationError> {
    if !path.exists() {
        return Err(ValidationError::FileNotFound);
    }

    let content =
        fs::read_to_string(path).map_err(|e| ValidationError::ReadError(e.to_string()))?;

    validate_spoiler_content(&content)
}

/// Validate spoiler log content and extract header info
pub fn validate_spoiler_content(content: &str) -> Result<SpoilerHeader, ValidationError> {
    let first_line = content
        .lines()
        .next()
        .ok_or(ValidationError::InvalidFormat("Empty file".to_string()))?;

    // Expected format: "Options and seed:12345 ..." or similar with "seed:NUMBER"
    let seed = extract_seed(first_line).ok_or(ValidationError::NoSeedFound)?;

    Ok(SpoilerHeader {
        seed,
        options_line: first_line.to_string(),
    })
}

/// Extract seed number from the options line
fn extract_seed(line: &str) -> Option<u64> {
    // Look for "seed:" followed by digits
    let seed_prefix = "seed:";
    let seed_start = line.find(seed_prefix)?;
    let after_prefix = &line[seed_start + seed_prefix.len()..];

    // Extract digits
    let digits: String = after_prefix
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();

    if digits.is_empty() {
        return None;
    }

    digits.parse().ok()
}

/// Read file content (for uploading to server)
pub fn read_spoiler_file(path: &Path) -> Result<String, ValidationError> {
    if !path.exists() {
        return Err(ValidationError::FileNotFound);
    }

    fs::read_to_string(path).map_err(|e| ValidationError::ReadError(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_seed() {
        assert_eq!(
            extract_seed("Options and seed:1851144969 other stuff"),
            Some(1851144969)
        );
        assert_eq!(extract_seed("seed:12345"), Some(12345));
        assert_eq!(extract_seed("no seed here"), None);
        assert_eq!(extract_seed("seed:"), None);
        assert_eq!(extract_seed("seed:abc"), None);
    }

    #[test]
    fn test_validate_content() {
        let content = "Options and seed:1851144969 fog:true\nChapel of Anticipation\n";
        let header = validate_spoiler_content(content).unwrap();
        assert_eq!(header.seed, 1851144969);
    }

    #[test]
    fn test_validate_invalid() {
        let content = "Some random file content\nNo seed here\n";
        assert!(validate_spoiler_content(content).is_err());
    }
}
