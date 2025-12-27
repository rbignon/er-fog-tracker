//! Entity utilities
//!
//! Functions for identifying and classifying game entities,
//! particularly fog gate randomizer entities and teleport animations.

use super::constants::{Animation, FOG_RANDO_ENTITY_MAX, FOG_RANDO_ENTITY_MIN};

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

/// Get teleport type name from animation ID
///
/// Returns the name of the teleport type if the animation ID corresponds
/// to a known teleportation animation, or None otherwise.
///
/// # Examples
///
/// ```
/// use fog_rando_tracker::core::entity_utils::get_teleport_type;
///
/// assert_eq!(get_teleport_type(60060), Some("FOG"));
/// assert_eq!(get_teleport_type(60490), Some("WAYGATE"));
/// assert_eq!(get_teleport_type(12345), None);
/// ```
pub fn get_teleport_type(anim_id: u32) -> Option<&'static str> {
    Animation::from_anim_id(anim_id).and_then(|a| a.teleport_label())
}

/// Check if an animation ID is a teleportation animation
///
/// Returns true only for teleport animations, not for other known animations.
pub fn is_teleport_animation(anim_id: u32) -> bool {
    Animation::from_anim_id(anim_id)
        .map(|a| a.is_teleport())
        .unwrap_or(false)
}

/// Get a human-readable label for an animation ID
///
/// Returns a label for known animations, "IDLE?" for 0,
/// or an empty string for unknown animations.
pub fn get_animation_label(anim_id: u32) -> &'static str {
    if let Some(anim) = Animation::from_anim_id(anim_id) {
        return anim.name();
    }

    // Special case: 0 is idle/no animation
    if anim_id == 0 {
        return "IDLE?";
    }

    ""
}

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // is_fog_rando_entity tests
    // =========================================================================

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

    // =========================================================================
    // get_teleport_type tests
    // =========================================================================

    #[test]
    fn test_teleport_type_fog() {
        assert_eq!(get_teleport_type(60060), Some("FOG"));
    }

    #[test]
    fn test_teleport_type_waygate() {
        assert_eq!(get_teleport_type(60490), Some("WAYGATE"));
    }

    #[test]
    fn test_teleport_type_sending_gates() {
        // Both blue and red sending gates should return same type
        assert_eq!(get_teleport_type(60470), Some("SENDING_GATE"));
        assert_eq!(get_teleport_type(60472), Some("SENDING_GATE"));
    }

    #[test]
    fn test_teleport_type_medal() {
        assert_eq!(get_teleport_type(50340), Some("MEDAL"));
    }

    #[test]
    fn test_teleport_type_special() {
        assert_eq!(get_teleport_type(60460), Some("BACK_TO_ENTRANCE"));
        assert_eq!(get_teleport_type(60010), Some("HORNED_REMAINS"));
        assert_eq!(get_teleport_type(12202126), Some("LIURNIA_TOWER_DOOR"));
        assert_eq!(get_teleport_type(12020210), Some("POST_BOSS_WARP"));
        assert_eq!(get_teleport_type(68110), Some("ERDTREE_BURN"));
        assert_eq!(get_teleport_type(67010), Some("PLACIDUSAX_LIE_DOWN"));
    }

    #[test]
    fn test_teleport_type_unknown() {
        assert_eq!(get_teleport_type(0), None);
        assert_eq!(get_teleport_type(12345), None);
        assert_eq!(get_teleport_type(99999), None);
    }

    #[test]
    fn test_teleport_type_non_teleport_animations() {
        // Non-teleport animations should return None
        assert_eq!(get_teleport_type(50230), None); // ItemUseMemory
        assert_eq!(get_teleport_type(63000), None); // Spawn
    }

    // =========================================================================
    // is_teleport_animation tests
    // =========================================================================

    #[test]
    fn test_is_teleport_animation() {
        assert!(is_teleport_animation(60060));
        assert!(is_teleport_animation(60490));
        assert!(!is_teleport_animation(0));
        assert!(!is_teleport_animation(12345));
    }

    #[test]
    fn test_is_teleport_animation_non_teleport() {
        // Non-teleport animations should return false
        assert!(!is_teleport_animation(50230)); // ItemUseMemory
        assert!(!is_teleport_animation(63000)); // Spawn
    }

    // =========================================================================
    // get_animation_label tests
    // =========================================================================

    #[test]
    fn test_animation_labels() {
        assert_eq!(get_animation_label(60060), "FOG_WALL");
        assert_eq!(get_animation_label(60470), "SENDING_GATE_BLUE");
        assert_eq!(get_animation_label(60472), "SENDING_GATE_RED");
        assert_eq!(get_animation_label(50230), "ITEM_USE_MEMORY");
        assert_eq!(get_animation_label(63000), "SPAWN");
        assert_eq!(get_animation_label(0), "IDLE?");
        assert_eq!(get_animation_label(99999), "");
    }
}
