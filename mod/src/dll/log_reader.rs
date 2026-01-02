//! Log file reader for uploading recent logs to the server

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::time::Duration;

use chrono::{DateTime, Local, NaiveDateTime};

/// Errors that can occur when reading logs
#[derive(Debug)]
pub enum LogReadError {
    /// Log file not found or couldn't be opened
    FileNotFound,
    /// Log file is empty
    EmptyFile,
    /// No logs within the requested duration
    NoRecentLogs,
    /// IO error while reading
    IoError(std::io::Error),
}

impl std::fmt::Display for LogReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LogReadError::FileNotFound => write!(f, "Log file not found"),
            LogReadError::EmptyFile => write!(f, "Log file is empty"),
            LogReadError::NoRecentLogs => write!(f, "No logs in the requested time range"),
            LogReadError::IoError(e) => write!(f, "IO error: {}", e),
        }
    }
}

/// Read logs from the last `duration` from the log file.
///
/// The log format expected is tracing's default format:
/// `YYYY-MM-DDTHH:MM:SS.mmm LEVEL message`
///
/// Returns the concatenated log lines as a string.
pub fn read_recent_logs(log_path: &Path, duration: Duration) -> Result<String, LogReadError> {
    let file = File::open(log_path).map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            LogReadError::FileNotFound
        } else {
            LogReadError::IoError(e)
        }
    })?;

    let reader = BufReader::new(file);
    let cutoff = Local::now() - chrono::Duration::from_std(duration).unwrap_or_default();

    let mut recent_lines = Vec::new();
    let mut has_any_lines = false;

    for line in reader.lines() {
        let line = line.map_err(LogReadError::IoError)?;
        has_any_lines = true;

        // Try to parse timestamp from beginning of line
        // Format: "2024-01-15T14:30:45.123 INFO message"
        if let Some(timestamp) = parse_log_timestamp(&line) {
            if timestamp >= cutoff {
                recent_lines.push(line);
            }
        } else {
            // Lines without timestamps (continuation) are included if we're already capturing
            if !recent_lines.is_empty() {
                recent_lines.push(line);
            }
        }
    }

    if !has_any_lines {
        return Err(LogReadError::EmptyFile);
    }

    if recent_lines.is_empty() {
        return Err(LogReadError::NoRecentLogs);
    }

    Ok(recent_lines.join("\n"))
}

/// Parse a timestamp from the beginning of a log line.
///
/// Supports multiple formats:
/// - ISO 8601 with Z: `2026-01-02T16:36:20.988342Z` (tracing with UTC)
/// - ISO 8601 with T: `2024-01-15T14:30:45.123456`
/// - Space separator: `2024-01-15 14:30:45.123456`
fn parse_log_timestamp(line: &str) -> Option<DateTime<Local>> {
    // Try ISO 8601 format with Z suffix (UTC timezone)
    // e.g., "2026-01-02T16:36:20.988342Z DEBUG ..."
    if line.len() >= 27 && line.as_bytes().get(26) == Some(&b'Z') {
        let timestamp_str = line.get(..26)?; // "YYYY-MM-DDTHH:MM:SS.ffffff"
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%dT%H:%M:%S%.f") {
            return Some(DateTime::from_naive_utc_and_offset(
                naive,
                *Local::now().offset(),
            ));
        }
    }

    // Try ISO 8601 format with T separator (no timezone)
    // e.g., "2024-01-15T14:30:45.123456 INFO ..."
    if let Some(timestamp_str) = line.get(..26) {
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%dT%H:%M:%S%.f") {
            return Some(DateTime::from_naive_utc_and_offset(
                naive,
                *Local::now().offset(),
            ));
        }
    }

    // Try space separator format with microseconds
    // e.g., "2024-01-15 14:30:45.123456 INFO ..."
    if let Some(timestamp_str) = line.get(..26) {
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%d %H:%M:%S%.f") {
            return Some(DateTime::from_naive_utc_and_offset(
                naive,
                *Local::now().offset(),
            ));
        }
    }

    // Try shorter timestamp without fractional seconds (T separator)
    if let Some(timestamp_str) = line.get(..19) {
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%dT%H:%M:%S") {
            return Some(DateTime::from_naive_utc_and_offset(
                naive,
                *Local::now().offset(),
            ));
        }
    }

    // Try shorter timestamp without fractional seconds (space separator)
    if let Some(timestamp_str) = line.get(..19) {
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%d %H:%M:%S") {
            return Some(DateTime::from_naive_utc_and_offset(
                naive,
                *Local::now().offset(),
            ));
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_log_timestamp() {
        // ISO 8601 with Z suffix (UTC)
        let line = "2026-01-02T16:36:20.988342Z DEBUG [ANIM] test message";
        let ts = parse_log_timestamp(line);
        assert!(ts.is_some(), "Should parse ISO 8601 with Z suffix");

        // ISO 8601 with T separator
        let line = "2024-01-15T14:30:45.123456 INFO fog_rando_tracker: test message";
        let ts = parse_log_timestamp(line);
        assert!(ts.is_some(), "Should parse ISO 8601 with T separator");

        // Space separator with microseconds
        let line = "2024-01-15 14:30:45.123456  INFO fog_rando_tracker: test message";
        let ts = parse_log_timestamp(line);
        assert!(ts.is_some(), "Should parse space separator format");

        // Space separator without fractional seconds
        let line = "2024-01-15 14:30:45  INFO fog_rando_tracker: test message";
        let ts = parse_log_timestamp(line);
        assert!(ts.is_some(), "Should parse without fractional seconds");

        // No timestamp
        let line = "INFO this line has no timestamp";
        let ts = parse_log_timestamp(line);
        assert!(
            ts.is_none(),
            "Should return None for lines without timestamp"
        );
    }
}
