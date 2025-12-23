// ============================================================
// PARSER - Converts spoiler log text to graph data
// ============================================================

// UUID generator with fallback for browsers without crypto.randomUUID
function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    // Fallback using crypto.getRandomValues
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
        (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16)
    );
}

export const SpoilerLogParser = {
    // Patterns that ALWAYS indicate a one-way connection
    alwaysOneWayPatterns: [
        /sending gate/i,
        /abducted/i,
        /dying/i,
        /burning the Sealing Tree/i,
        /using the Pureblood/i,
        /Hole-Laden Necklace/i,
        /return to entrance/i,
        /O Mother/i,
        /resting in the coffin/i,
        /using the coffin/i,
        /lying down/i,
        /warp to/i,
        /warp after/i,
    ],

    // "arriving at/in/from" is only one-way if the SOURCE contains a teleport mechanism
    // These patterns are checked in the source part when "arriving" is found in target
    teleportSourcePatterns: [
        /sending gate/i,
        /abducted/i,
        /coffin/i,
        /Pureblood/i,
        /Hole-Laden/i,
        /burning/i,
        /warp/i,
        /Horned Remains/i,
        /lying down/i,
    ],

    // Patterns to skip (metadata lines)
    skipPatterns: [
        /^Options and seed:/,
        /^Key item hash:/,
        /^Mod directories/,
        /^Connecting/,
        /^Main fixup/,
        /^Areas before/,
        /^Other areas/,
        /^This spoiler/,
        /^For each area/,
        /^Paired warps/,
        /^How to get/,
        /^- Find/,
        /^- The first/,
        /^- Repeat/,
        /^If you're stuck/,
        /^you haven't/,
        /^>>>/,
        /^Optional areas:/,
        /^Finished/,
        /^Writing/,
        /^\$ /,
        /^\d+ entrances/,
        /^Done$/,
        /^C:\\/,
    ],

    // Patterns that indicate details in connection descriptions
    detailPatterns: [
        /\s*\(before\s/i,
        /\s*\(after\s/i,
        /\s*\(at\s/i,
        /\s*\(using\s/i,
        /\s*\(in\s/i,
        /\s*\(the\s/i,
        /\s*\(on\s/i,
        /\s*\(arriving\s/i,
        /\s*\(opening\s/i,
        /\s*\(dropping\s/i,
        /\s*\(with\s/i,
        /\s*\(accessing\s/i,
        /\s*\(defeating\s/i,
        /\s*\(completing\s/i,
        /\s*\(riding\s/i,
        /\s*\(jumping\s/i,
        /\s*\(resting\s/i,
        /\s*\(touching\s/i,
        /\s*\(lying\s/i,
        /\s*\(burning\s/i,
        /\s*\(getting\s/i,
        /\s*\(touching\s/i,
        /\s*\(traversing\s/i,
        /\s*\(going\s/i,
        /\s*\(return\s/i,
        /\s*\(unlocking\s/i,
        /\s*\(instead\s/i,
        /\s*\(warp\s/i,
        /\s*\(outside\s/i,
        /\s*\(behind\s/i,
        /\s*\(past\s/i,
        /\s*\(up\s/i,
        /\s*\(down\s/i,
        /\s*\(backwards\s/i,
    ],

    shouldSkipLine(line) {
        const trimmed = line.trim();
        if (!trimmed) return true;
        return this.skipPatterns.some(pattern => pattern.test(trimmed));
    },

    parseAreaLine(line) {
        // Area lines are not indented
        if (line.startsWith('  ') || line.startsWith('\t')) return null;
        if (this.shouldSkipLine(line)) return null;

        const isBoss = line.includes('<<<<<');
        const lineClean = line.replace(/<<<<</, '').trim();

        // Extract scaling info
        const scalingMatch = lineClean.match(/\(scaling:\s*([^)]+)\)/);
        const scaling = scalingMatch ? scalingMatch[1].trim() : null;

        // Extract area name (everything before the parenthesis)
        const nameMatch = lineClean.match(/^([^(]+)/);
        if (nameMatch) {
            const name = nameMatch[1].trim();
            if (name) {
                return { name, isBoss, scaling };
            }
        }
        return null;
    },

    extractAreaAndDetails(text) {
        for (const pattern of this.detailPatterns) {
            const match = text.match(pattern);
            if (match) {
                const areaName = text.substring(0, match.index).trim();
                // Extract details in parentheses
                const detailsMatch = text.substring(match.index).match(/\(([^)]+)\)/);
                const details = detailsMatch ? detailsMatch[1] : '';
                return { areaName, details };
            }
        }
        return { areaName: text.trim(), details: '' };
    },

    parseConnectionLine(line) {
        const trimmed = line.trim();
        let connType, content;

        if (trimmed.startsWith('Random:')) {
            connType = 'random';
            content = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('Preexisting:')) {
            connType = 'preexisting';
            content = trimmed.substring(12).trim();
        } else {
            return null;
        }

        if (!content.includes(' --> ')) return null;

        const parts = content.split(' --> ');
        if (parts.length !== 2) return null;

        const [sourcePart, targetPart] = parts;

        const { areaName: source, details: sourceDetails } = this.extractAreaAndDetails(sourcePart);
        const { areaName: target, details: targetDetails } = this.extractAreaAndDetails(targetPart);

        // Extract "using an item from..." or "using items from..." before cleaning
        let requiredItemFrom = null;
        const usingMatch = content.match(/,\s*using (?:an )?items? from\s+(.+?)$/i);
        if (usingMatch) {
            requiredItemFrom = usingMatch[1].trim();
        }

        // Clean up "using ... from..."
        const cleanSource = source.split(', using')[0].trim();
        const cleanTarget = target.split(', using')[0].trim();

        // Detect if this is a one-way connection based on description patterns
        // For Random links, check if any one-way pattern matches
        let isInherentlyOneWay = false;
        if (connType === 'random') {
            // Check patterns that always indicate one-way
            if (this.alwaysOneWayPatterns.some(pattern => pattern.test(content))) {
                isInherentlyOneWay = true;
            }
            // Check "arriving" - only one-way if source contains teleport mechanism
            else if (/arriving (at|in|from)/i.test(content)) {
                // Check if source part contains a teleport mechanism
                isInherentlyOneWay = this.teleportSourcePatterns.some(pattern => pattern.test(sourcePart));
            }
        }

        return {
            id: generateUUID(),
            source: cleanSource,
            target: cleanTarget,
            type: connType,
            sourceDetails,
            targetDetails,
            requiredItemFrom,
            isInherentlyOneWay,
        };
    },

    parse(text) {
        const lines = text.split('\n');
        const areas = new Map();
        const connections = [];
        let areaOrder = 0;
        let inOptionalSection = false;
        const metadata = {};

        // Extract seed from first line
        const firstLine = lines[0] || '';
        const seedMatch = firstLine.match(/seed:(\d+)/);
        if (seedMatch) {
            metadata.seed = seedMatch[1];
        }
        metadata.options = firstLine.trim();

        for (const line of lines) {
            // Stop at optional areas section
            if (line.trim() === 'Optional areas:') {
                inOptionalSection = true;
                break;
            }

            // Try to parse as area
            const areaInfo = this.parseAreaLine(line);
            if (areaInfo) {
                if (!areas.has(areaInfo.name)) {
                    areas.set(areaInfo.name, {
                        id: areaInfo.name,
                        isBoss: areaInfo.isBoss,
                        scaling: areaInfo.scaling,
                        order: areaOrder++,
                    });
                } else {
                    // Update existing area with boss/scaling info if we have it
                    // (area may have been created earlier from a connection line)
                    const existing = areas.get(areaInfo.name);
                    if (areaInfo.isBoss) existing.isBoss = true;
                    if (areaInfo.scaling) existing.scaling = areaInfo.scaling;
                }
                continue;
            }

            // Try to parse as connection
            if (line.startsWith('  ') || line.startsWith('\t')) {
                const conn = this.parseConnectionLine(line);
                if (conn) {
                    // Ensure areas exist
                    if (!areas.has(conn.source)) {
                        areas.set(conn.source, {
                            id: conn.source,
                            isBoss: false,
                            scaling: null,
                            order: areaOrder++,
                        });
                    }
                    if (!areas.has(conn.target)) {
                        areas.set(conn.target, {
                            id: conn.target,
                            isBoss: false,
                            scaling: null,
                            order: areaOrder++,
                        });
                    }
                    connections.push(conn);
                }
            }
        }

        return {
            nodes: Array.from(areas.values()),
            links: connections,
            metadata,
        };
    },
};

// ============================================================
// KEY ITEMS / ACTIONS DETECTION
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
 * Parse the zones list from requiredItemFrom field
 * @param {string} zonesText - The zones text (single zone or "A; B; C" format)
 * @returns {string[]} Array of zone names
 */
export function parseRequiredItemZones(zonesText) {
    if (!zonesText) return [];
    return zonesText
        .split('; ')
        .map(z => z.trim())
        .filter(z => z.length > 0);
}
