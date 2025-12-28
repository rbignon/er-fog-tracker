// ============================================================
// KEY ITEMS - Utilities for key item detection in fog log descriptions
// ============================================================

// Known key items and actions that can be mentioned in fog log descriptions
const KNOWN_KEY_ITEMS = [
    'Hole-Laden Necklace',
    'Discarded Palace Key',
    'Carian Inverted Statue',
    'Drawing-Room Key',
    "Pureblood Knight's Medal",
    'O Mother',
    'Rusty Key',
    'Academy Glintstone Key',
    'Dectus Medallion',
    'Haligtree Secret Medallion',
    'Rold Medallion',
    'Cursemark of Death',
    'Dark Moon Ring',
    'Well Depths Key',
];

// Known actions that require items (not items themselves but indicate item requirements)
const KNOWN_ACTIONS = ['burning the Sealing Tree', 'acquiring enough Great Runes'];

/**
 * Extract key item or action name from link description text
 * @param {string} sourceDetails - The source details text
 * @param {string} targetDetails - The target details text
 * @returns {string|null} The item/action name if found, null otherwise
 */
export function extractRequiredItemFromDescription(sourceDetails, targetDetails) {
    const text = `${sourceDetails || ''} ${targetDetails || ''}`;

    // Check for known key items
    for (const item of KNOWN_KEY_ITEMS) {
        if (text.includes(item)) {
            return item;
        }
    }

    // Check for known actions
    for (const action of KNOWN_ACTIONS) {
        if (text.toLowerCase().includes(action.toLowerCase())) {
            return action;
        }
    }

    return null;
}

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
