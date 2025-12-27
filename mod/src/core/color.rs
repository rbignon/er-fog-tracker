//! Color utilities
//!
//! Functions for parsing and converting colors.

/// Parse hex color "#RRGGBB" to [f32; 4] for ImGui
///
/// Returns RGBA as floats in the range [0.0, 1.0].
/// Falls back to white if the hex string is invalid.
///
/// # Examples
///
/// ```
/// use fog_rando_tracker::core::color::parse_hex_color;
///
/// let red = parse_hex_color("#FF0000", 1.0);
/// assert_eq!(red, [1.0, 0.0, 0.0, 1.0]);
///
/// let semi_transparent_green = parse_hex_color("#00FF00", 0.5);
/// assert_eq!(semi_transparent_green, [0.0, 1.0, 0.0, 0.5]);
/// ```
pub fn parse_hex_color(hex: &str, alpha: f32) -> [f32; 4] {
    let hex = hex.trim_start_matches('#');
    if hex.len() < 6 {
        return [1.0, 1.0, 1.0, alpha]; // Fallback to white
    }
    let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(255);
    let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(255);
    let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(255);
    [r as f32 / 255.0, g as f32 / 255.0, b as f32 / 255.0, alpha]
}

/// Convert RGBA [f32; 4] back to hex "#RRGGBB" (ignoring alpha)
pub fn to_hex_color(rgba: [f32; 4]) -> String {
    let r = (rgba[0] * 255.0).round() as u8;
    let g = (rgba[1] * 255.0).round() as u8;
    let b = (rgba[2] * 255.0).round() as u8;
    format!("#{:02X}{:02X}{:02X}", r, g, b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_hex_color_basic() {
        assert_eq!(parse_hex_color("#FF0000", 1.0), [1.0, 0.0, 0.0, 1.0]); // Red
        assert_eq!(parse_hex_color("#00FF00", 1.0), [0.0, 1.0, 0.0, 1.0]); // Green
        assert_eq!(parse_hex_color("#0000FF", 1.0), [0.0, 0.0, 1.0, 1.0]); // Blue
    }

    #[test]
    fn test_parse_hex_color_black_white() {
        assert_eq!(parse_hex_color("#000000", 1.0), [0.0, 0.0, 0.0, 1.0]); // Black
        assert_eq!(parse_hex_color("#FFFFFF", 1.0), [1.0, 1.0, 1.0, 1.0]); // White
    }

    #[test]
    fn test_parse_hex_color_alpha() {
        assert_eq!(parse_hex_color("#FF0000", 0.5), [1.0, 0.0, 0.0, 0.5]);
        assert_eq!(parse_hex_color("#FF0000", 0.0), [1.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn test_parse_hex_color_without_hash() {
        assert_eq!(parse_hex_color("FF0000", 1.0), [1.0, 0.0, 0.0, 1.0]);
    }

    #[test]
    fn test_parse_hex_color_mixed_case() {
        assert_eq!(parse_hex_color("#ff0000", 1.0), [1.0, 0.0, 0.0, 1.0]);
        assert_eq!(parse_hex_color("#Ff00fF", 1.0), [1.0, 0.0, 1.0, 1.0]);
    }

    #[test]
    fn test_parse_hex_color_invalid_fallback() {
        // Too short - fallback to white
        assert_eq!(parse_hex_color("#FFF", 1.0), [1.0, 1.0, 1.0, 1.0]);
        assert_eq!(parse_hex_color("", 1.0), [1.0, 1.0, 1.0, 1.0]);
        assert_eq!(parse_hex_color("#", 1.0), [1.0, 1.0, 1.0, 1.0]);
    }

    #[test]
    fn test_parse_hex_color_invalid_chars() {
        // Invalid hex chars fallback to 255 per component
        assert_eq!(parse_hex_color("#GGGGGG", 1.0), [1.0, 1.0, 1.0, 1.0]);
    }

    #[test]
    fn test_parse_hex_color_config_defaults() {
        // Test the actual config default values
        assert_eq!(
            parse_hex_color("#141414", 0.7),
            [0.078431375, 0.078431375, 0.078431375, 0.7]
        );
        assert_eq!(
            parse_hex_color("#808080", 1.0),
            [0.5019608, 0.5019608, 0.5019608, 1.0]
        );
        assert_eq!(
            parse_hex_color("#80FF80", 1.0),
            [0.5019608, 1.0, 0.5019608, 1.0]
        );
    }

    #[test]
    fn test_to_hex_color() {
        assert_eq!(to_hex_color([1.0, 0.0, 0.0, 1.0]), "#FF0000");
        assert_eq!(to_hex_color([0.0, 1.0, 0.0, 1.0]), "#00FF00");
        assert_eq!(to_hex_color([0.0, 0.0, 1.0, 1.0]), "#0000FF");
        assert_eq!(to_hex_color([0.0, 0.0, 0.0, 1.0]), "#000000");
        assert_eq!(to_hex_color([1.0, 1.0, 1.0, 1.0]), "#FFFFFF");
    }

    #[test]
    fn test_roundtrip() {
        let colors = [
            "#FF0000", "#00FF00", "#0000FF", "#000000", "#FFFFFF", "#808080",
        ];
        for hex in colors {
            let rgba = parse_hex_color(hex, 1.0);
            let back = to_hex_color(rgba);
            assert_eq!(back, hex, "Roundtrip failed for {}", hex);
        }
    }
}
