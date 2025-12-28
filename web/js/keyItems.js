// ============================================================
// KEY ITEMS - Utilities for key item zone parsing
// ============================================================

/**
 * Parse zones from a "required_item_from" field
 * @param {string} zonesText - Semicolon-separated zone list
 * @returns {string[]} Array of zone names
 */
export function parseRequiredItemZones(zonesText) {
    if (!zonesText) return [];
    return zonesText
        .split('; ')
        .map(z => z.trim())
        .filter(z => z.length > 0);
}
