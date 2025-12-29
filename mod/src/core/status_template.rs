//! Status template rendering
//!
//! Parses and renders status line templates with variable substitution.
//!
//! # Template syntax
//!
//! - Variables: `{zone}`, `{discovered}`, `{total}`, `{progress}`, `{status}`, `{map}`,
//!   `{deaths}`, `{igt}`, `{runes}`, `{kindling}`, `{scaling}`, `{rune_icons}`, `{kindling_icon}`, `{death_icon}`
//! - Colors: `{variable:color}` where color is a name or hex code
//!   - Named colors: `red`, `green`, `blue`, `yellow`, `orange`, `cyan`, `magenta`, `gray`, `white`
//!   - Hex colors: `#RRGGBB` (e.g., `#FF0000` for red)
//!   - Config colors: `discovered`, `undiscovered`, `disabled` (reference overlay config)
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
//!     scaling: Some("Scaling: tier 1".to_string()),
//! };
//!
//! // Simple template
//! let result = render_template("{zone}$>{status} {discovered}/{total}", &ctx);
//! assert_eq!(result.lines.len(), 1);
//!
//! // With colors
//! let result = render_template("{zone:blue}$>{discovered:green}/{total}", &ctx);
//! assert_eq!(result.lines.len(), 1);
//! ```

/// Marker character used to wrap the status indicator for colored rendering
/// The UI layer should detect this and apply the appropriate color.
pub const STATUS_MARKER_START: char = '\x01';
pub const STATUS_MARKER_END: char = '\x02';

/// Color specification for template text
#[derive(Debug, Clone, PartialEq)]
pub enum TemplateColor {
    /// Default text color (from config text_color)
    Default,
    /// Status indicator color (dynamic based on connection state)
    Status,
    /// Reference to config discovered_color
    Discovered,
    /// Reference to config undiscovered_color
    Undiscovered,
    /// Reference to config text_disabled_color
    Disabled,
    /// Named color
    Named(NamedColor),
    /// Hex color (#RRGGBB)
    Hex(String),
}

/// Predefined named colors
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum NamedColor {
    Red,
    Green,
    Blue,
    Yellow,
    Orange,
    Cyan,
    Magenta,
    Gray,
    White,
}

impl NamedColor {
    /// Convert to RGBA values
    pub fn to_rgba(self) -> [f32; 4] {
        match self {
            NamedColor::Red => [1.0, 0.0, 0.0, 1.0],
            NamedColor::Green => [0.0, 1.0, 0.0, 1.0],
            NamedColor::Blue => [0.4, 0.6, 1.0, 1.0], // Lighter blue for readability
            NamedColor::Yellow => [1.0, 1.0, 0.0, 1.0],
            NamedColor::Orange => [1.0, 0.65, 0.0, 1.0],
            NamedColor::Cyan => [0.0, 1.0, 1.0, 1.0],
            NamedColor::Magenta => [1.0, 0.0, 1.0, 1.0],
            NamedColor::Gray => [0.5, 0.5, 0.5, 1.0],
            NamedColor::White => [1.0, 1.0, 1.0, 1.0],
        }
    }
}

/// Parse a color string into a TemplateColor
///
/// Accepts:
/// - Named colors: "red", "green", "blue", etc.
/// - Config references: "discovered", "undiscovered", "disabled"
/// - Hex colors: "#RRGGBB" or "RRGGBB"
pub fn parse_template_color(color_str: &str) -> Option<TemplateColor> {
    let color_lower = color_str.to_lowercase();
    match color_lower.as_str() {
        // Named colors
        "red" => Some(TemplateColor::Named(NamedColor::Red)),
        "green" => Some(TemplateColor::Named(NamedColor::Green)),
        "blue" => Some(TemplateColor::Named(NamedColor::Blue)),
        "yellow" => Some(TemplateColor::Named(NamedColor::Yellow)),
        "orange" => Some(TemplateColor::Named(NamedColor::Orange)),
        "cyan" => Some(TemplateColor::Named(NamedColor::Cyan)),
        "magenta" | "purple" => Some(TemplateColor::Named(NamedColor::Magenta)),
        "gray" | "grey" => Some(TemplateColor::Named(NamedColor::Gray)),
        "white" => Some(TemplateColor::Named(NamedColor::White)),
        // Config references
        "discovered" => Some(TemplateColor::Discovered),
        "undiscovered" => Some(TemplateColor::Undiscovered),
        "disabled" => Some(TemplateColor::Disabled),
        // Hex color
        _ => {
            let hex = color_str.trim_start_matches('#');
            if hex.len() == 6 && hex.chars().all(|c| c.is_ascii_hexdigit()) {
                Some(TemplateColor::Hex(format!("#{}", hex.to_uppercase())))
            } else {
                None
            }
        }
    }
}

/// A span of text with optional color
#[derive(Debug, Clone, PartialEq)]
pub struct TextSpan {
    /// The text content
    pub text: String,
    /// Optional color for this span
    pub color: TemplateColor,
}

/// A content span that can be either text or special content (like icons)
#[derive(Debug, Clone, PartialEq)]
pub enum ContentSpan {
    /// Text span with optional color
    Text(TextSpan),
    /// Rune icons placeholder (UI layer handles actual rendering)
    RuneIcons,
    /// Kindling icon placeholder (UI layer handles actual rendering)
    KindlingIcon,
    /// Death icon placeholder (UI layer handles actual rendering)
    DeathIcon,
}

impl ContentSpan {
    /// Create a text content span
    pub fn text(text: String, color: TemplateColor) -> Self {
        Self::Text(TextSpan { text, color })
    }

    /// Check if this is a text span
    pub fn as_text(&self) -> Option<&TextSpan> {
        match self {
            Self::Text(span) => Some(span),
            _ => None,
        }
    }
}

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
    /// Zone scaling text (e.g., "Scaling: tier 1, previously 2")
    pub scaling: Option<String>,
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
            scaling: None,
        }
    }
}

/// A segment of rendered content within a line
#[derive(Debug, Clone, PartialEq)]
pub enum LineSegment {
    /// Content aligned to the left
    Left(Vec<ContentSpan>),
    /// Content aligned to the right (content after `$>`)
    Right(Vec<ContentSpan>),
}

/// A single rendered line
#[derive(Debug, Clone, PartialEq)]
pub struct RenderedLine {
    pub segments: Vec<LineSegment>,
}

impl RenderedLine {
    /// Create a line with only left-aligned content
    pub fn left_only(spans: Vec<ContentSpan>) -> Self {
        Self {
            segments: vec![LineSegment::Left(spans)],
        }
    }

    /// Create a line with left and right aligned content
    pub fn left_right(left: Vec<ContentSpan>, right: Vec<ContentSpan>) -> Self {
        Self {
            segments: vec![LineSegment::Left(left), LineSegment::Right(right)],
        }
    }

    /// Get the left-aligned content spans (if any)
    pub fn left_spans(&self) -> Option<&[ContentSpan]> {
        self.segments.iter().find_map(|s| match s {
            LineSegment::Left(spans) => Some(spans.as_slice()),
            _ => None,
        })
    }

    /// Get the right-aligned content spans (if any)
    pub fn right_spans(&self) -> Option<&[ContentSpan]> {
        self.segments.iter().find_map(|s| match s {
            LineSegment::Right(spans) => Some(spans.as_slice()),
            _ => None,
        })
    }

    /// Get the left-aligned text as a plain string (for compatibility)
    ///
    /// Note: This only includes text spans, not special content like rune icons.
    pub fn left_text(&self) -> Option<String> {
        self.left_spans().map(|spans| {
            spans
                .iter()
                .filter_map(|s| s.as_text().map(|t| t.text.as_str()))
                .collect()
        })
    }

    /// Get the right-aligned text as a plain string (for compatibility)
    ///
    /// Note: This only includes text spans, not special content like rune icons.
    pub fn right_text(&self) -> Option<String> {
        self.right_spans().map(|spans| {
            spans
                .iter()
                .filter_map(|s| s.as_text().map(|t| t.text.as_str()))
                .collect()
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

/// Get the value for a variable name
fn get_variable_value(name: &str, ctx: &TemplateContext) -> Option<String> {
    match name {
        "zone" => Some(
            ctx.zone
                .as_deref()
                .unwrap_or(&ctx.zone_unknown_text)
                .to_string(),
        ),
        "discovered" => Some(ctx.discovered.to_string()),
        "total" => Some(ctx.total.to_string()),
        "progress" => {
            let progress = if ctx.total > 0 {
                (ctx.discovered * 100) / ctx.total
            } else {
                0
            };
            Some(progress.to_string())
        }
        "map" => Some(ctx.map_id.as_deref().unwrap_or("").to_string()),
        "deaths" => Some(ctx.deaths.map(|d| d.to_string()).unwrap_or_default()),
        "igt" => Some(ctx.igt_ms.map(format_igt).unwrap_or_default()),
        "runes" => Some(ctx.runes.map(|r| r.to_string()).unwrap_or_default()),
        "kindling" => Some(ctx.kindling.map(|k| k.to_string()).unwrap_or_default()),
        "scaling" => Some(ctx.scaling.as_deref().unwrap_or("").to_string()),
        "status" => None, // Special handling
        _ => None,
    }
}

/// Substitute variables in a template string, returning content spans
fn substitute_variables(
    template: &str,
    ctx: &TemplateContext,
    has_status: &mut bool,
) -> Vec<ContentSpan> {
    let mut spans: Vec<ContentSpan> = Vec::new();
    let mut literal_start = 0;
    let chars: Vec<char> = template.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        if chars[i] == '{' {
            // Find the closing brace
            if let Some(end) = chars[i..].iter().position(|&c| c == '}') {
                let end = i + end;

                // Add any literal text before this variable
                if i > literal_start {
                    let literal: String = chars[literal_start..i].iter().collect();
                    if !literal.is_empty() {
                        spans.push(ContentSpan::text(literal, TemplateColor::Default));
                    }
                }

                // Parse the variable content: "name" or "name:color"
                let content: String = chars[i + 1..end].iter().collect();
                let (var_name, color) = if let Some(colon_pos) = content.find(':') {
                    let name = &content[..colon_pos];
                    let color_str = &content[colon_pos + 1..];
                    let color = parse_template_color(color_str).unwrap_or(TemplateColor::Default);
                    (name.to_string(), color)
                } else {
                    (content.clone(), TemplateColor::Default)
                };

                // Get the variable value and create span
                if var_name == "status" {
                    if ctx.server_enabled {
                        *has_status = true;
                        spans.push(ContentSpan::text("●".to_string(), TemplateColor::Status));
                    }
                    // If server disabled, status is empty - no span added
                } else if var_name == "rune_icons" {
                    spans.push(ContentSpan::RuneIcons);
                } else if var_name == "kindling_icon" {
                    spans.push(ContentSpan::KindlingIcon);
                } else if var_name == "death_icon" {
                    spans.push(ContentSpan::DeathIcon);
                } else if let Some(value) = get_variable_value(&var_name, ctx) {
                    if !value.is_empty() {
                        spans.push(ContentSpan::text(value, color));
                    }
                } else {
                    // Unknown variable - keep it as literal
                    let unknown: String = chars[i..=end].iter().collect();
                    spans.push(ContentSpan::text(unknown, TemplateColor::Default));
                }

                literal_start = end + 1;
                i = end + 1;
                continue;
            }
        }
        i += 1;
    }

    // Add any remaining literal text
    if literal_start < chars.len() {
        let literal: String = chars[literal_start..].iter().collect();
        if !literal.is_empty() {
            spans.push(ContentSpan::text(literal, TemplateColor::Default));
        }
    }

    // If no spans were created, add an empty one
    if spans.is_empty() {
        spans.push(ContentSpan::text(String::new(), TemplateColor::Default));
    }

    spans
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
            scaling: Some("Scaling: tier 1, previously 2".to_string()),
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
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));
    }

    #[test]
    fn test_zone_unknown() {
        let ctx = TemplateContext {
            zone: None,
            zone_unknown_text: "(unknown zone)".to_string(),
            ..default_ctx()
        };
        let result = render_template("{zone}", &ctx);
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("(unknown zone)")
        );
    }

    #[test]
    fn test_discovered_total() {
        let ctx = default_ctx();
        let result = render_template("{discovered}/{total}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("42/100"));
    }

    #[test]
    fn test_progress() {
        let ctx = default_ctx();
        let result = render_template("{progress}%", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("42%"));
    }

    #[test]
    fn test_progress_zero_total() {
        let ctx = TemplateContext {
            total: 0,
            ..default_ctx()
        };
        let result = render_template("{progress}%", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("0%"));
    }

    #[test]
    fn test_map_id() {
        let ctx = default_ctx();
        let result = render_template("Map: {map}", &ctx);
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("Map: m60_44_36_00")
        );
    }

    #[test]
    fn test_map_id_none() {
        let ctx = TemplateContext {
            map_id: None,
            ..default_ctx()
        };
        let result = render_template("Map: {map}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Map: "));
    }

    #[test]
    fn test_deaths() {
        let ctx = default_ctx();
        let result = render_template("Deaths: {deaths}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Deaths: 5"));
    }

    #[test]
    fn test_deaths_none() {
        let ctx = TemplateContext {
            deaths: None,
            ..default_ctx()
        };
        let result = render_template("Deaths: {deaths}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Deaths: "));
    }

    #[test]
    fn test_igt() {
        let ctx = default_ctx();
        let result = render_template("IGT: {igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("IGT: 1:02:03"));
    }

    #[test]
    fn test_igt_none() {
        let ctx = TemplateContext {
            igt_ms: None,
            ..default_ctx()
        };
        let result = render_template("IGT: {igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("IGT: "));
    }

    #[test]
    fn test_igt_formatting() {
        // Test various IGT values
        let ctx = TemplateContext {
            igt_ms: Some(0),
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("0:00:00"));

        let ctx = TemplateContext {
            igt_ms: Some(59999), // 59.999 seconds
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("0:00:59"));

        let ctx = TemplateContext {
            igt_ms: Some(3661000), // 1:01:01
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("1:01:01"));

        let ctx = TemplateContext {
            igt_ms: Some(36000000), // 10:00:00
            ..default_ctx()
        };
        let result = render_template("{igt}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("10:00:00"));
    }

    // -------------------------------------------------------------------------
    // Runes and Kindling tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_runes() {
        let ctx = default_ctx();
        let result = render_template("Runes: {runes}/8", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Runes: 3/8"));
    }

    #[test]
    fn test_runes_none() {
        let ctx = TemplateContext {
            runes: None,
            ..default_ctx()
        };
        let result = render_template("R:{runes}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("R:"));
    }

    #[test]
    fn test_kindling() {
        let ctx = default_ctx();
        let result = render_template("Kindling: {kindling}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Kindling: 2"));
    }

    #[test]
    fn test_kindling_none() {
        let ctx = TemplateContext {
            kindling: None,
            ..default_ctx()
        };
        let result = render_template("K:{kindling}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("K:"));
    }

    #[test]
    fn test_runes_and_kindling_combined() {
        let ctx = TemplateContext {
            runes: Some(5),
            kindling: Some(3),
            ..default_ctx()
        };
        let result = render_template("{runes}/8 | K:{kindling}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("5/8 | K:3"));
    }

    // -------------------------------------------------------------------------
    // Scaling tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_scaling() {
        let ctx = default_ctx();
        let result = render_template("{scaling}", &ctx);
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("Scaling: tier 1, previously 2")
        );
    }

    #[test]
    fn test_scaling_none() {
        let ctx = TemplateContext {
            scaling: None,
            ..default_ctx()
        };
        let result = render_template("S:{scaling}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("S:"));
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
        assert_eq!(result.lines[0].left_text().as_deref(), Some(""));
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
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));
        assert_eq!(result.lines[0].right_text().as_deref(), Some("42/100"));
    }

    #[test]
    fn test_right_alignment_with_status() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{status} {discovered}/{total}", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));
        let right = result.lines[0].right_text().unwrap();
        assert!(right.contains('●'));
        assert!(right.contains("42/100"));
    }

    #[test]
    fn test_no_right_alignment() {
        let ctx = default_ctx();
        let result = render_template("{zone} - {discovered}/{total}", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("Limgrave - 42/100")
        );
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
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));
        assert_eq!(result.lines[1].left_text().as_deref(), Some("42/100"));
    }

    #[test]
    fn test_multiline_with_alignment() {
        let ctx = default_ctx();
        let result = render_template("{zone}$>{status}$n{discovered}/{total} discovered", &ctx);
        assert_eq!(result.lines.len(), 2);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));
        assert!(result.lines[0].right_text().unwrap().contains('●'));
        assert_eq!(
            result.lines[1].left_text().as_deref(),
            Some("42/100 discovered")
        );
    }

    // -------------------------------------------------------------------------
    // Extract/split status tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_extract_status_indicator() {
        let ctx = default_ctx();
        let result = render_template("{status} test", &ctx);
        // With the new span-based system, status is rendered as a separate span
        // The extract_status_indicator function works with legacy marker-based strings
        let text = result.lines[0].left_text().unwrap();

        // In the new system, the text is "● test" without markers
        // The legacy function won't find markers, so we test the actual content
        assert!(text.contains('●'));
        assert!(text.contains("test"));
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
        // With new span-based system, we check spans directly
        let spans = result.lines[0].left_spans().unwrap();

        // Should have 3 spans: "before ", "●", " after"
        assert_eq!(spans.len(), 3);
        let s0 = spans[0].as_text().unwrap();
        let s1 = spans[1].as_text().unwrap();
        let s2 = spans[2].as_text().unwrap();
        assert_eq!(s0.text, "before ");
        assert_eq!(s0.color, TemplateColor::Default);
        assert_eq!(s1.text, "●");
        assert_eq!(s1.color, TemplateColor::Status);
        assert_eq!(s2.text, " after");
        assert_eq!(s2.color, TemplateColor::Default);
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
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Limgrave"));

        // Check right side spans
        let right_spans = result.lines[0].right_spans().unwrap();
        // Should be: "●", " ", "42", "/", "100"
        // Actually: "●" (Status), " " (Default), "42" (Default), "/" (Default), "100" (Default)
        assert!(right_spans.iter().any(|s| {
            s.as_text()
                .map(|t| t.text == "●" && t.color == TemplateColor::Status)
                .unwrap_or(false)
        }));
        let right_text = result.lines[0].right_text().unwrap();
        assert!(right_text.contains("42/100"));
    }

    // -------------------------------------------------------------------------
    // Edge cases
    // -------------------------------------------------------------------------

    #[test]
    fn test_empty_template() {
        let ctx = default_ctx();
        let result = render_template("", &ctx);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].left_text().as_deref(), Some(""));
    }

    #[test]
    fn test_literal_text_only() {
        let ctx = default_ctx();
        let result = render_template("Hello World", &ctx);
        assert_eq!(result.lines[0].left_text().as_deref(), Some("Hello World"));
    }

    #[test]
    fn test_unknown_variable_preserved() {
        let ctx = default_ctx();
        let result = render_template("{unknown}", &ctx);
        // Unknown variables are not substituted
        assert_eq!(result.lines[0].left_text().as_deref(), Some("{unknown}"));
    }

    #[test]
    fn test_multiple_same_variable() {
        let ctx = default_ctx();
        let result = render_template("{zone} | {zone}", &ctx);
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("Limgrave | Limgrave")
        );
    }

    // -------------------------------------------------------------------------
    // Color parsing tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_parse_named_colors() {
        assert_eq!(
            parse_template_color("red"),
            Some(TemplateColor::Named(NamedColor::Red))
        );
        assert_eq!(
            parse_template_color("GREEN"),
            Some(TemplateColor::Named(NamedColor::Green))
        );
        assert_eq!(
            parse_template_color("Blue"),
            Some(TemplateColor::Named(NamedColor::Blue))
        );
        assert_eq!(
            parse_template_color("yellow"),
            Some(TemplateColor::Named(NamedColor::Yellow))
        );
        assert_eq!(
            parse_template_color("orange"),
            Some(TemplateColor::Named(NamedColor::Orange))
        );
        assert_eq!(
            parse_template_color("cyan"),
            Some(TemplateColor::Named(NamedColor::Cyan))
        );
        assert_eq!(
            parse_template_color("magenta"),
            Some(TemplateColor::Named(NamedColor::Magenta))
        );
        assert_eq!(
            parse_template_color("purple"),
            Some(TemplateColor::Named(NamedColor::Magenta))
        );
        assert_eq!(
            parse_template_color("gray"),
            Some(TemplateColor::Named(NamedColor::Gray))
        );
        assert_eq!(
            parse_template_color("grey"),
            Some(TemplateColor::Named(NamedColor::Gray))
        );
        assert_eq!(
            parse_template_color("white"),
            Some(TemplateColor::Named(NamedColor::White))
        );
    }

    #[test]
    fn test_parse_config_colors() {
        assert_eq!(
            parse_template_color("discovered"),
            Some(TemplateColor::Discovered)
        );
        assert_eq!(
            parse_template_color("undiscovered"),
            Some(TemplateColor::Undiscovered)
        );
        assert_eq!(
            parse_template_color("disabled"),
            Some(TemplateColor::Disabled)
        );
    }

    #[test]
    fn test_parse_hex_colors() {
        assert_eq!(
            parse_template_color("#FF0000"),
            Some(TemplateColor::Hex("#FF0000".to_string()))
        );
        assert_eq!(
            parse_template_color("#00ff00"),
            Some(TemplateColor::Hex("#00FF00".to_string()))
        );
        assert_eq!(
            parse_template_color("0088FF"),
            Some(TemplateColor::Hex("#0088FF".to_string()))
        );
    }

    #[test]
    fn test_parse_invalid_colors() {
        assert_eq!(parse_template_color("invalid"), None);
        assert_eq!(parse_template_color("#FFF"), None); // Too short
        assert_eq!(parse_template_color("#GGGGGG"), None); // Invalid hex
        assert_eq!(parse_template_color(""), None);
    }

    #[test]
    fn test_variable_with_named_color() {
        let ctx = default_ctx();
        let result = render_template("{zone:blue}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        let s = spans[0].as_text().unwrap();
        assert_eq!(s.text, "Limgrave");
        assert_eq!(s.color, TemplateColor::Named(NamedColor::Blue));
    }

    #[test]
    fn test_variable_with_hex_color() {
        let ctx = default_ctx();
        let result = render_template("{zone:#FF0000}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        let s = spans[0].as_text().unwrap();
        assert_eq!(s.text, "Limgrave");
        assert_eq!(s.color, TemplateColor::Hex("#FF0000".to_string()));
    }

    #[test]
    fn test_variable_with_config_color() {
        let ctx = default_ctx();
        let result = render_template("{zone:discovered}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        let s = spans[0].as_text().unwrap();
        assert_eq!(s.text, "Limgrave");
        assert_eq!(s.color, TemplateColor::Discovered);
    }

    #[test]
    fn test_multiple_variables_with_colors() {
        let ctx = default_ctx();
        let result = render_template("{zone:blue} - {discovered:green}/{total}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        // Should have: "Limgrave" (blue), " - " (default), "42" (green), "/" (default), "100" (default)
        assert!(spans.iter().any(|s| {
            s.as_text()
                .map(|t| t.text == "Limgrave" && t.color == TemplateColor::Named(NamedColor::Blue))
                .unwrap_or(false)
        }));
        assert!(spans.iter().any(|s| {
            s.as_text()
                .map(|t| t.text == "42" && t.color == TemplateColor::Named(NamedColor::Green))
                .unwrap_or(false)
        }));
        assert!(spans.iter().any(|s| {
            s.as_text()
                .map(|t| t.text == "100" && t.color == TemplateColor::Default)
                .unwrap_or(false)
        }));
    }

    #[test]
    fn test_invalid_color_falls_back_to_default() {
        let ctx = default_ctx();
        let result = render_template("{zone:notacolor}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        let s = spans[0].as_text().unwrap();
        assert_eq!(s.text, "Limgrave");
        assert_eq!(s.color, TemplateColor::Default);
    }

    // -------------------------------------------------------------------------
    // Rune icons tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_rune_icons_produces_marker() {
        let ctx = default_ctx();
        let result = render_template("{rune_icons}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0], ContentSpan::RuneIcons);
    }

    #[test]
    fn test_rune_icons_with_text() {
        let ctx = default_ctx();
        let result = render_template("Runes: {rune_icons} done", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        // Should have: "Runes: ", RuneIcons, " done"
        assert_eq!(spans.len(), 3);
        assert_eq!(spans[0].as_text().unwrap().text, "Runes: ");
        assert_eq!(spans[1], ContentSpan::RuneIcons);
        assert_eq!(spans[2].as_text().unwrap().text, " done");
    }

    #[test]
    fn test_rune_icons_not_in_text_output() {
        let ctx = default_ctx();
        let result = render_template("Before {rune_icons} After", &ctx);

        // left_text() should skip RuneIcons and only return text
        assert_eq!(
            result.lines[0].left_text().as_deref(),
            Some("Before  After")
        );
    }

    // -------------------------------------------------------------------------
    // Kindling icon tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_kindling_icon_produces_marker() {
        let ctx = default_ctx();
        let result = render_template("{kindling_icon}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0], ContentSpan::KindlingIcon);
    }

    #[test]
    fn test_kindling_icon_with_text() {
        let ctx = default_ctx();
        let result = render_template("{kindling_icon}{kindling}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        // Should have: KindlingIcon, "2"
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0], ContentSpan::KindlingIcon);
        assert_eq!(spans[1].as_text().unwrap().text, "2");
    }

    #[test]
    fn test_kindling_icon_not_in_text_output() {
        let ctx = default_ctx();
        let result = render_template("K:{kindling_icon}{kindling}", &ctx);

        // left_text() should skip KindlingIcon and only return text
        assert_eq!(result.lines[0].left_text().as_deref(), Some("K:2"));
    }

    // -------------------------------------------------------------------------
    // Death icon tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_death_icon_produces_marker() {
        let ctx = default_ctx();
        let result = render_template("{death_icon}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0], ContentSpan::DeathIcon);
    }

    #[test]
    fn test_death_icon_with_text() {
        let ctx = default_ctx();
        let result = render_template("{death_icon}{deaths}", &ctx);
        let spans = result.lines[0].left_spans().unwrap();

        // Should have: DeathIcon, "5"
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0], ContentSpan::DeathIcon);
        assert_eq!(spans[1].as_text().unwrap().text, "5");
    }

    #[test]
    fn test_named_color_to_rgba() {
        assert_eq!(NamedColor::Red.to_rgba(), [1.0, 0.0, 0.0, 1.0]);
        assert_eq!(NamedColor::Green.to_rgba(), [0.0, 1.0, 0.0, 1.0]);
        assert_eq!(NamedColor::White.to_rgba(), [1.0, 1.0, 1.0, 1.0]);
    }
}
