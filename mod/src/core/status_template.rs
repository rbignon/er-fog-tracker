//! Status template rendering
//!
//! Parses and renders status line templates with variable substitution.
//!
//! # Template syntax
//!
//! - Variables: `{zone}`, `{discovered}`, `{total}`, `{progress}`, `{status}`, `{map}`,
//!   `{deaths}`, `{igt}`, `{runes}`, `{kindling}`
//! - Markers: `$n` (newline), `$>` (right-align rest of line)
//!
//! # Examples
//!
//! ```
//! use fog_rando_tracker::core::status_template::{TemplateContext, render_template};
//!
//! let ctx = TemplateContext {
//!     zone: Some("Limgrave".to_string()),
//!     zone_unknown_text: "(unknown)".to_string(),
//!     discovered: 42,
//!     total: 100,
//!     server_enabled: true,
//!     server_connected: true,
//!     map_id: Some("m60_44_36_00".to_string()),
//!     deaths: Some(5),
//!     igt_ms: Some(3600000),
//!     runes: Some(3),
//!     kindling: Some(2),
//! };
//!
//! let result = render_template("{zone}$>{status} {discovered}/{total}", &ctx);
//! assert_eq!(result.lines.len(), 1);
//! ```

/// Marker character used to wrap the status indicator for colored rendering
/// The UI layer should detect this and apply the appropriate color.
pub const STATUS_MARKER_START: char = '\x01';
pub const STATUS_MARKER_END: char = '\x02';

/// Context for template variable substitution
#[derive(Debug, Clone)]
pub struct TemplateContext {
    /// Current zone name, or None if unknown
    pub zone: Option<String>,
    /// Text to show when zone is unknown
    pub zone_unknown_text: String,
    /// Number of discovered links
    pub discovered: u32,
    /// Total number of random links
    pub total: u32,
    /// Whether server integration is enabled
    pub server_enabled: bool,
    /// Whether currently connected to server
    pub server_connected: bool,
    /// Current map ID (formatted, e.g., "m60_44_36_00")
    pub map_id: Option<String>,
    /// Death count (total deaths for the character)
    pub deaths: Option<u32>,
    /// In-game time in milliseconds
    pub igt_ms: Option<u32>,
    /// Number of Great Runes possessed (deduplicated, 0-8)
    pub runes: Option<u32>,
    /// Number of Messmer's Kindling items
    pub kindling: Option<u32>,
}

impl Default for TemplateContext {
    fn default() -> Self {
        Self {
            zone: None,
            zone_unknown_text: "(unknown)".to_string(),
            discovered: 0,
            total: 0,
            server_enabled: false,
            server_connected: false,
            map_id: None,
            deaths: None,
            igt_ms: None,
            runes: None,
            kindling: None,
        }
    }
}

/// A segment of rendered text within a line
#[derive(Debug, Clone, PartialEq)]
pub enum LineSegment {
    /// Text aligned to the left
    Left(String),
    /// Text aligned to the right (content after `$>`)
    Right(String),
}

/// A single rendered line
#[derive(Debug, Clone, PartialEq)]
pub struct RenderedLine {
    pub segments: Vec<LineSegment>,
}

impl RenderedLine {
    /// Create a line with only left-aligned content
    pub fn left_only(text: String) -> Self {
        Self {
            segments: vec![LineSegment::Left(text)],
        }
    }

    /// Create a line with left and right aligned content
    pub fn left_right(left: String, right: String) -> Self {
        Self {
            segments: vec![LineSegment::Left(left), LineSegment::Right(right)],
        }
    }

    /// Get the left-aligned text (if any)
    pub fn left_text(&self) -> Option<&str> {
        self.segments.iter().find_map(|s| match s {
            LineSegment::Left(text) => Some(text.as_str()),
            _ => None,
        })
    }

    /// Get the right-aligned text (if any)
    pub fn right_text(&self) -> Option<&str> {
        self.segments.iter().find_map(|s| match s {
            LineSegment::Right(text) => Some(text.as_str()),
            _ => None,
        })
    }
}

/// Result of rendering a template
#[derive(Debug, Clone, PartialEq)]
pub struct RenderedStatus {
    /// Rendered lines
    pub lines: Vec<RenderedLine>,
    /// Whether the status indicator is present (for coloring)
    pub has_status_indicator: bool,
}

/// Render a status template with the given context
///
/// # Arguments
///
/// * `template` - The template string to render
/// * `ctx` - The context providing variable values
///
/// # Returns
///
/// A `RenderedStatus` containing the rendered lines and metadata.
pub fn render_template(template: &str, ctx: &TemplateContext) -> RenderedStatus {
    let mut has_status_indicator = false;

    // Split by $n for multiple lines
    let line_templates: Vec<&str> = template.split("$n").collect();

    let lines: Vec<RenderedLine> = line_templates
        .iter()
        .map(|line_template| {
            // Split by $> for right alignment
            let parts: Vec<&str> = line_template.splitn(2, "$>").collect();

            let left = substitute_variables(parts[0], ctx, &mut has_status_indicator);

            if parts.len() > 1 {
                let right = substitute_variables(parts[1], ctx, &mut has_status_indicator);
                RenderedLine::left_right(left, right)
            } else {
                RenderedLine::left_only(left)
            }
        })
        .collect();

    RenderedStatus {
        lines,
        has_status_indicator,
    }
}

/// Format milliseconds as HH:MM:SS
fn format_igt(ms: u32) -> String {
    let total_seconds = ms / 1000;
    let hours = total_seconds / 3600;
    let minutes = (total_seconds % 3600) / 60;
    let seconds = total_seconds % 60;
    format!("{:01}:{:02}:{:02}", hours, minutes, seconds)
}

/// Substitute variables in a template string
fn substitute_variables(template: &str, ctx: &TemplateContext, has_status: &mut bool) -> String {
    let mut result = template.to_string();

    // {zone} - zone name or unknown text
    let zone_value = ctx
        .zone
        .as_deref()
        .unwrap_or(&ctx.zone_unknown_text)
        .to_string();
    result = result.replace("{zone}", &zone_value);

    // {discovered}
    result = result.replace("{discovered}", &ctx.discovered.to_string());

    // {total}
    result = result.replace("{total}", &ctx.total.to_string());

    // {progress} - percentage (0 if total is 0)
    let progress = if ctx.total > 0 {
        (ctx.discovered * 100) / ctx.total
    } else {
        0
    };
    result = result.replace("{progress}", &progress.to_string());

    // {map} - map ID or empty
    let map_value = ctx.map_id.as_deref().unwrap_or("");
    result = result.replace("{map}", map_value);

    // {deaths} - death count
    let deaths_value = ctx.deaths.map(|d| d.to_string()).unwrap_or_default();
    result = result.replace("{deaths}", &deaths_value);

    // {igt} - in-game time formatted as H:MM:SS
    let igt_value = ctx.igt_ms.map(format_igt).unwrap_or_default();
    result = result.replace("{igt}", &igt_value);

    // {runes} - Great Runes count
    let runes_value = ctx.runes.map(|r| r.to_string()).unwrap_or_default();
    result = result.replace("{runes}", &runes_value);

    // {kindling} - Messmer's Kindling count
    let kindling_value = ctx.kindling.map(|k| k.to_string()).unwrap_or_default();
    result = result.replace("{kindling}", &kindling_value);

    // {status} - connection indicator with markers for coloring
    if result.contains("{status}") {
        let status_value = if ctx.server_enabled {
            *has_status = true;
            format!("{}●{}", STATUS_MARKER_START, STATUS_MARKER_END)
        } else {
            String::new()
        };
        result = result.replace("{status}", &status_value);
    }

    result
}

/// Extract the status indicator from rendered text for separate coloring
///
/// Returns the text with the status indicator removed, and the indicator itself.
/// This is useful for the UI layer to render the indicator with a different color.
pub fn extract_status_indicator(text: &str) -> (String, Option<&'static str>) {
    let marker_pattern = format!("{}●{}", STATUS_MARKER_START, STATUS_MARKER_END);
    if text.contains(&marker_pattern) {
        let cleaned = text.replace(&marker_pattern, "");
        (cleaned, Some("●"))
    } else {
        (text.to_string(), None)
    }
}

/// Split text around the status indicator for colored rendering
///
/// Returns (before, has_indicator, after) where the UI can render:
/// - before in normal color
/// - "●" in status color (if has_indicator)
/// - after in normal color
pub fn split_around_status(text: &str) -> (String, bool, String) {
    let marker_pattern = format!("{}●{}", STATUS_MARKER_START, STATUS_MARKER_END);
    if let Some(pos) = text.find(&marker_pattern) {
        let before = text[..pos].to_string();
        let after = text[pos + marker_pattern.len()..].to_string();
        (before, true, after)
    } else {
        (text.to_string(), false, String::new())
    }
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn default_ctx() -> TemplateContext {
        TemplateContext {
            zone: Some("Limgrave".to_string()),
            zone_unknown_text: "(traverse a fog to identify)".to_string(),
            discovered: 42,
            total: 100,
            server_enabled: true,
            server_connected: true,
            map_id: Some("m60_44_36_00".to_string()),
            deaths: Some(5),
            igt_ms: Some(3723000), // 1:02:03
            runes: Some(3),
            kindling: Some(2),
        }
    }

    // -------------------------------------------------------------------------
    // Basic substitution tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_simple_zone() {
        let ctx = default_ctx();
        let result = render_template("{zone}", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));
    }

    #[test]
    fn test_zone_unknown() {
        let ctx = TemplateContext {
            zone: None,
            zone_unknown_text: "(unknown zone)".to_string(),
            ..default_ctx()
        };
        let result = render_template("{zone}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("(unknown zone)"));
    }

    #[test]
    fn test_discovered_total() {
        let ctx = default_ctx();
        let result = render_template("{discovered}/{total}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("42/100"));
    }

    #[test]
    fn test_progress() {
        let ctx = default_ctx();
        let result = render_template("{progress}%", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("42%"));
    }

    #[test]
    fn test_progress_zero_total() {
        let ctx = TemplateContext {
            total: 0,
            ..default_ctx()
        };
        let result = render_template("{progress}%", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("0%"));
    }

    #[test]
    fn test_map_id() {
        let ctx = default_ctx();
        let result = render_template("Map: {map}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Map: m60_44_36_00"));
    }

    #[test]
    fn test_map_id_none() {
        let ctx = TemplateContext {
            map_id: None,
            ..default_ctx()
        };
        let result = render_template("Map: {map}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Map: "));
    }

    #[test]
    fn test_deaths() {
        let ctx = default_ctx();
        let result = render_template("Deaths: {deaths}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Deaths: 5"));
    }

    #[test]
    fn test_deaths_none() {
        let ctx = TemplateContext {
            deaths: None,
            ..default_ctx()
        };
        let result = render_template("Deaths: {deaths}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Deaths: "));
    }

    #[test]
    fn test_igt() {
        let ctx = default_ctx();
        let result = render_template("IGT: {igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("IGT: 1:02:03"));
    }

    #[test]
    fn test_igt_none() {
        let ctx = TemplateContext {
            igt_ms: None,
            ..default_ctx()
        };
        let result = render_template("IGT: {igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("IGT: "));
    }

    #[test]
    fn test_igt_formatting() {
        // Test various IGT values
        let ctx = TemplateContext {
            igt_ms: Some(0),
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("0:00:00"));

        let ctx = TemplateContext {
            igt_ms: Some(59999), // 59.999 seconds
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("0:00:59"));

        let ctx = TemplateContext {
            igt_ms: Some(3661000), // 1:01:01
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("1:01:01"));

        let ctx = TemplateContext {
            igt_ms: Some(36000000), // 10:00:00
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("10:00:00"));
    }

    // -------------------------------------------------------------------------
    // Runes and Kindling tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_runes() {
        let ctx = default_ctx();
        let result = render_template("Runes: {runes}/8", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Runes: 3/8"));
    }

    #[test]
    fn test_runes_none() {
        let ctx = TemplateContext {
            runes: None,
            ..default_ctx()
        };
        let result = render_template("R:{runes}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("R:"));
    }

    #[test]
    fn test_kindling() {
        let ctx = default_ctx();
        let result = render_template("Kindling: {kindling}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Kindling: 2"));
    }

    #[test]
    fn test_kindling_none() {
        let ctx = TemplateContext {
            kindling: None,
            ..default_ctx()
        };
        let result = render_template("K:{kindling}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("K:"));
    }

    #[test]
    fn test_runes_and_kindling_combined() {
        let ctx = TemplateContext {
            runes: Some(5),
            kindling: Some(3),
            ..default_ctx()
        };
        let result = render_template("{runes}/8 | K:{kindling}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("5/8 | K:3"));
    }

    // -------------------------------------------------------------------------
    // Status indicator tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_status_server_enabled() {
        let ctx = default_ctx();
        let result = render_template("{status}", &ctx);
        assert!(result.has_status_indicator);
        let text = result.lines[0].left_text().unwrap();
        assert!(text.contains('●'));
    }

    #[test]
    fn test_status_server_disabled() {
        let ctx = TemplateContext {
            server_enabled: false,
            ..default_ctx()
        };
        let result = render_template("{status}", &ctx);
        assert!(!result.has_status_indicator);
        assert_eq!(result.lines[0].left_text(), Some(""));
    }

    #[test]
    fn test_status_with_text() {
        let ctx = default_ctx();
        let result = render_template("{status} {discovered}/{total}", &ctx);
        let text = result.lines[0].left_text().unwrap();
        // Should contain the indicator and the stats
        assert!(text.contains('●'));
        assert!(text.contains("42/100"));
    }

    // -------------------------------------------------------------------------
    // Right alignment tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_right_alignment() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{discovered}/{total}", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));
        assert_eq!(result.lines[0].right_text(), Some("42/100"));
    }

    #[test]
    fn test_right_alignment_with_status() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{status} {discovered}/{total}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));
        let right = result.lines[0].right_text().unwrap();
        assert!(right.contains('●'));
        assert!(right.contains("42/100"));
    }

    #[test]
    fn test_no_right_alignment() {
        let ctx = default_ctx();
        let result = render_template("{zone} - {discovered}/{total}", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave - 42/100"));
        assert_eq!(result.lines[0].right_text(), None);
    }

    // -------------------------------------------------------------------------
    // Multiline tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_multiline() {
        let ctx = default_ctx();
        let result = render_template("{zone}$n{discovered}/{total}", &ctx);
        assert_eq!(result.lines.len(), 2);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));
        assert_eq!(result.lines[1].left_text(), Some("42/100"));
    }

    #[test]
    fn test_multiline_with_alignment() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{status}$n{discovered}/{total} discovered", &ctx);
        assert_eq!(result.lines.len(), 2);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));
        assert!(result.lines[0].right_text().unwrap().contains('●'));
        assert_eq!(result.lines[1].left_text(), Some("42/100 discovered"));
    }

    // -------------------------------------------------------------------------
    // Extract/split status tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_extract_status_indicator() {
        let ctx = default_ctx();
        let result = render_template("{status} test", &ctx);
        let text = result.lines[0].left_text().unwrap();

        let (cleaned, indicator) = extract_status_indicator(text);
        assert_eq!(indicator, Some("●"));
        assert_eq!(cleaned, " test");
    }

    #[test]
    fn test_extract_status_indicator_none() {
        let (cleaned, indicator) = extract_status_indicator("no indicator here");
        assert_eq!(indicator, None);
        assert_eq!(cleaned, "no indicator here");
    }

    #[test]
    fn test_split_around_status() {
        let ctx = default_ctx();
        let result = render_template("before {status} after", &ctx);
        let text = result.lines[0].left_text().unwrap();

        let (before, has, after) = split_around_status(text);
        assert!(has);
        assert_eq!(before, "before ");
        assert_eq!(after, " after");
    }

    #[test]
    fn test_split_around_status_none() {
        let (before, has, after) = split_around_status("no indicator");
        assert!(!has);
        assert_eq!(before, "no indicator");
        assert_eq!(after, "");
    }

    // -------------------------------------------------------------------------
    // Default template (reproduces current behavior)
    // -------------------------------------------------------------------------

    #[test]
    fn test_default_template() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{status} {discovered}/{total}", &ctx);

        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave"));

        let right = result.lines[0].right_text().unwrap();
        let (before, has_indicator, after) = split_around_status(right);
        assert!(has_indicator);
        assert_eq!(before, "");
        assert_eq!(after, " 42/100");
    }

    // -------------------------------------------------------------------------
    // Edge cases
    // -------------------------------------------------------------------------

    #[test]
    fn test_empty_template() {
        let ctx = default_ctx();
        let result = render_template("", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text(), Some(""));
    }

    #[test]
    fn test_literal_text_only() {
        let ctx = default_ctx();
        let result = render_template("Hello World", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Hello World"));
    }

    #[test]
    fn test_unknown_variable_preserved() {
        let ctx = default_ctx();
        let result = render_template("{unknown}", &ctx);
        // Unknown variables are not substituted
        assert_eq!(result.lines[0].left_text(), Some("{unknown}"));
    }

    #[test]
    fn test_multiple_same_variable() {
        let ctx = default_ctx();
        let result = render_template("{zone} | {zone}", &ctx);
        assert_eq!(result.lines[0].left_text(), Some("Limgrave | Limgrave"));
    }
}
