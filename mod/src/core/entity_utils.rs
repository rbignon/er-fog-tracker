//! Entity utilities
//!
//! Functions for identifying and classifying game entities,
//! particularly fog gate randomizer entities.
//!
//! Animation-related utilities are in the `animations` module.

use super::constants::{FOG_RANDO_ENTITY_MAX, FOG_RANDO_ENTITY_MIN};

/// Check if an entity ID is from Fog Gate Randomizer
///
/// Fog Gate Randomizer generates sequential entity IDs in the range
/// 755890000 to 755899999.
///
/// # Examples
///
/// ```
/// use fog_rando_tracker::core::entity_utils::is_fog_rando_entity;
///
/// assert!(is_fog_rando_entity(755890042));
/// assert!(!is_fog_rando_entity(12345));
/// ```
pub fn is_fog_rando_entity(entity_id: u32) -> bool {
    entity_id >= FOG_RANDO_ENTITY_MIN && entity_id <= FOG_RANDO_ENTITY_MAX
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fog_rando_entity_in_range() {
        assert!(is_fog_rando_entity(755890000)); // Min
        assert!(is_fog_rando_entity(755890001));
        assert!(is_fog_rando_entity(755895000)); // Middle
        assert!(is_fog_rando_entity(755899998));
        assert!(is_fog_rando_entity(755899999)); // Max
    }

    #[test]
    fn test_fog_rando_entity_boundaries() {
        assert!(!is_fog_rando_entity(755889999)); // Just below min
        assert!(!is_fog_rando_entity(755900000)); // Just above max
    }

    #[test]
    fn test_fog_rando_entity_common_values() {
        assert!(!is_fog_rando_entity(0));
        assert!(!is_fog_rando_entity(12345));
        assert!(!is_fog_rando_entity(1000000));
        assert!(!is_fog_rando_entity(u32::MAX));
    }
}
