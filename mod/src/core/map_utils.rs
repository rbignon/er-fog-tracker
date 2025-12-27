//! Map ID utilities
//!
//! Functions for formatting and parsing Elden Ring map IDs.
//! Map IDs are 32-bit values encoded as mWW_XX_YY_DD.

/// Format a map_id as a string "mWW_XX_YY_DD"
///
/// The map_id is a 32-bit value where:
/// - WW (bits 24-31): World/region number
/// - XX (bits 16-23): Area number
/// - YY (bits 8-15): Sub-area number
/// - DD (bits 0-7): Detail/variant number
///
/// # Examples
///
/// ```
/// use fog_rando_tracker::core::map_utils::format_map_id;
///
/// assert_eq!(format_map_id(0x3C2C2400), "m60_44_36_00");
/// ```
pub fn format_map_id(map_id: u32) -> String {
    let ww = (map_id >> 24) & 0xFF;
    let xx = (map_id >> 16) & 0xFF;
    let yy = (map_id >> 8) & 0xFF;
    let dd = map_id & 0xFF;
    format!("m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd)
}

/// Parse a map_id string "mWW_XX_YY_DD" back to u32
///
/// Returns None if the string is not a valid map_id format.
///
/// # Examples
///
/// ```
/// use fog_rando_tracker::core::map_utils::parse_map_id;
///
/// assert_eq!(parse_map_id("m60_44_36_00"), Some(0x3C2C2400));
/// assert_eq!(parse_map_id("invalid"), None);
/// ```
pub fn parse_map_id(s: &str) -> Option<u32> {
    let s = s.strip_prefix('m')?;
    let parts: Vec<&str> = s.split('_').collect();
    if parts.len() != 4 {
        return None;
    }

    let ww = parts[0].parse::<u32>().ok()?;
    let xx = parts[1].parse::<u32>().ok()?;
    let yy = parts[2].parse::<u32>().ok()?;
    let dd = parts[3].parse::<u32>().ok()?;

    if ww > 255 || xx > 255 || yy > 255 || dd > 255 {
        return None;
    }

    Some((ww << 24) | (xx << 16) | (yy << 8) | dd)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_map_id_limgrave() {
        // Limgrave: m60_44_36_00
        assert_eq!(format_map_id(0x3C2C2400), "m60_44_36_00");
    }

    #[test]
    fn test_format_map_id_stormveil() {
        // Stormveil Castle area
        assert_eq!(format_map_id(0x0A0A1000), "m10_10_16_00");
    }

    #[test]
    fn test_format_map_id_boundaries() {
        assert_eq!(format_map_id(0x00000000), "m00_00_00_00");
        assert_eq!(format_map_id(0xFFFFFFFF), "m255_255_255_255");
    }

    #[test]
    fn test_format_map_id_each_byte() {
        // Test that each byte position is correctly extracted
        assert_eq!(format_map_id(0x01000000), "m01_00_00_00");
        assert_eq!(format_map_id(0x00010000), "m00_01_00_00");
        assert_eq!(format_map_id(0x00000100), "m00_00_01_00");
        assert_eq!(format_map_id(0x00000001), "m00_00_00_01");
    }

    #[test]
    fn test_parse_map_id_valid() {
        assert_eq!(parse_map_id("m60_44_36_00"), Some(0x3C2C2400));
        assert_eq!(parse_map_id("m00_00_00_00"), Some(0x00000000));
        assert_eq!(parse_map_id("m255_255_255_255"), Some(0xFFFFFFFF));
    }

    #[test]
    fn test_parse_map_id_invalid() {
        assert_eq!(parse_map_id("invalid"), None);
        assert_eq!(parse_map_id("m60_44_36"), None); // Missing part
        assert_eq!(parse_map_id("60_44_36_00"), None); // Missing 'm' prefix
        assert_eq!(parse_map_id("m256_0_0_0"), None); // Value too large
        assert_eq!(parse_map_id("m-1_0_0_0"), None); // Negative value
        assert_eq!(parse_map_id(""), None);
    }

    #[test]
    fn test_roundtrip() {
        let test_values = [0x3C2C2400, 0x0A0A1000, 0x00000000, 0xFFFFFFFF, 0x12345678];

        for &original in &test_values {
            let formatted = format_map_id(original);
            let parsed = parse_map_id(&formatted);
            assert_eq!(
                parsed,
                Some(original),
                "Roundtrip failed for 0x{:08X} -> {} -> {:?}",
                original,
                formatted,
                parsed
            );
        }
    }
}
