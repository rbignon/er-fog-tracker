/**
 * REST API client for the fog-tracker backend.
 */

import { getAuthHeaders, logout } from './auth.js';
import { VERSION } from './version.js';

const DEFAULT_TIMEOUT_MS = 30000;

// Last seen server version (set after each API call)
let lastServerVersion = null;

/**
 * Base fetch wrapper with error handling and timeout.
 * @param {string} path - API path
 * @param {Object} options - Fetch options
 * @param {number} timeout - Timeout in ms (default 30s)
 */
async function apiFetch(path, options = {}, timeout = DEFAULT_TIMEOUT_MS) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(path, {
            ...options,
            signal: controller.signal,
            headers: {
                'Content-Type': 'application/json',
                'Client-Version': VERSION,
                ...getAuthHeaders(),
                ...options.headers,
            },
        });

        clearTimeout(timeoutId);

        // Store server version from response header
        const serverVersion = response.headers.get('Server-Version');
        if (serverVersion) {
            lastServerVersion = serverVersion;
        }

        if (!response.ok) {
            // Handle 401 Unauthorized - logout and redirect to landing
            if (response.status === 401) {
                logout();
                // logout() redirects, but throw anyway to stop execution
                const error = new Error('Session expired');
                error.status = 401;
                throw error;
            }

            const error = new Error(`API error: ${response.status}`);
            error.status = response.status;
            try {
                error.detail = (await response.json()).detail;
            } catch {
                error.detail = response.statusText;
            }
            throw error;
        }

        // Handle 204 No Content
        if (response.status === 204) {
            return null;
        }

        return response.json();
    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
            const error = new Error(`Request timeout after ${timeout}ms`);
            error.status = 0;
            error.detail = 'The server took too long to respond';
            throw error;
        }
        throw err;
    }
}

// =============================================================================
// Games API
// =============================================================================

/**
 * Create a new game.
 * @param {Object} data - { seed, label?, zonePairs, zones? }
 * @returns {Promise<{ gameId: string, created: boolean }>}
 */
export async function createGame({ seed, label, zonePairs, zones }) {
    return apiFetch('/api/games', {
        method: 'POST',
        body: JSON.stringify({
            seed,
            label: label || null,
            zone_links: zonePairs,
            zones: zones || null,
        }),
    });
}

/**
 * Get full game state.
 * @param {string} gameId - Game UUID
 * @returns {Promise<Object>} - Full game object
 */
export async function getGame(gameId) {
    return apiFetch(`/api/games/${gameId}`);
}

/**
 * Get current user's games.
 * @returns {Promise<{ games: Array }>}
 */
export async function getMyGames() {
    return apiFetch('/api/me/games');
}

/**
 * Delete a game (soft delete).
 * @param {string} gameId - Game UUID
 */
export async function deleteGame(gameId) {
    return apiFetch(`/api/games/${gameId}`, {
        method: 'DELETE',
    });
}

/**
 * Update game metadata.
 * @param {string} gameId - Game UUID
 * @param {Object} data - { label? }
 * @returns {Promise<Object>} - Updated game summary
 */
export async function updateGame(gameId, { label }) {
    return apiFetch(`/api/games/${gameId}`, {
        method: 'PATCH',
        body: JSON.stringify({ label }),
    });
}

// =============================================================================
// Spoiler API (public, no auth required)
// =============================================================================

/**
 * Parse a spoiler log via the server.
 * @param {string} spoilerLog - Raw spoiler log text
 * @returns {Promise<{ seed: number, zones: Array, zone_links: Array }>}
 */
export async function parseSpoilerLog(spoilerLog) {
    return apiFetch('/api/spoiler/parse', {
        method: 'POST',
        body: JSON.stringify({ spoiler_log: spoilerLog }),
    });
}

// =============================================================================
// Data Transformation (API snake_case → Frontend camelCase)
// =============================================================================

/**
 * Transform zones from API format to frontend format.
 * @param {Object|Array} zones - Zones from API (dict keyed by zone_key, or legacy array)
 * @returns {Array} Zones in frontend format (camelCase)
 */
export function transformZonesFromApi(zones) {
    // Handle both dict (new format) and array (legacy)
    const zoneArray = Array.isArray(zones) ? zones : Object.values(zones);
    return zoneArray.map((zone, index) => ({
        id: zone.id, // zone_key (primary identifier)
        name: zone.name, // display name (for labels)
        isBoss: zone.is_boss || false,
        scaling: zone.scaling || null,
        order: index,
    }));
}

/**
 * Transform zone links from API format to frontend format.
 * @param {Array} links - Links from API (snake_case)
 * @returns {Array} Links in frontend format (camelCase)
 */
export function transformLinksFromApi(links) {
    return links.map(link => ({
        id: link.id,
        source: link.source_id, // zone_key for D3 binding
        sourceName: link.source, // display name for labels
        target: link.target_id, // zone_key for D3 binding
        targetName: link.target, // display name for labels
        type: link.type,
        sourceDetails: link.source_details || '',
        targetDetails: link.target_details || '',
        requiredItem: link.required_item || null,
        requiredItemFrom: link.required_item_from || null,
        isOneWay: link.is_one_way || false,
    }));
}

/**
 * Transform zones from frontend format to API format.
 * @param {Array} nodes - Nodes in frontend format (camelCase)
 * @returns {Array} Zones in API format (snake_case)
 */
export function transformZonesToApi(nodes) {
    return nodes.map(node => ({
        id: node.id, // zone_key
        name: node.name || node.id, // display name (fallback to id)
        is_boss: node.isBoss || false,
        scaling: node.scaling || null,
    }));
}

/**
 * Transform zone links from frontend format to API format.
 * @param {Array} links - Links in frontend format (camelCase)
 * @param {Function} getLinkEndpoints - Function to resolve link endpoints
 * @returns {Array} Links in API format (snake_case)
 */
export function transformLinksToApi(links, getLinkEndpoints) {
    return links.map(link => {
        const { sourceId, targetId } = getLinkEndpoints(link);
        return {
            id: link.id,
            source: link.sourceName || sourceId, // display name
            source_id: sourceId, // zone_key
            target: link.targetName || targetId, // display name
            target_id: targetId, // zone_key
            type: link.type || 'random',
            source_details: link.sourceDetails || null,
            target_details: link.targetDetails || null,
            required_item: link.requiredItem || null,
            required_item_from: link.requiredItemFrom || null,
            is_one_way: link.isOneWay || false,
        };
    });
}

// =============================================================================
// Users API (public)
// =============================================================================

/**
 * Get public user info.
 * @param {string} username - Twitch username
 * @returns {Promise<{ username: string, displayName: string, avatarUrl: string | null }>}
 */
export async function getUser(username) {
    const data = await apiFetch(`/api/users/${username}`);
    return {
        username: data.username,
        displayName: data.display_name || data.username,
        avatarUrl: data.avatar_url || null,
    };
}

/**
 * Get public list of user's games.
 * @param {string} username - Twitch username
 * @returns {Promise<{ games: Array }>}
 */
export async function getUserGames(username) {
    return apiFetch(`/api/users/${username}/games`);
}

// =============================================================================
// Auth API
// =============================================================================

/**
 * Regenerate mod token for current user.
 * @returns {Promise<{ mod_token: string }>}
 */
export async function regenerateModToken() {
    return apiFetch('/auth/regenerate-mod-token', {
        method: 'POST',
    });
}

// =============================================================================
// Discovery API (REST fallback, prefer WebSocket)
// =============================================================================

/**
 * Create a discovery.
 * @param {string} gameId - Game UUID
 * @param {Object} data - { source_id, target_id, link_id? }
 * @returns {Promise<{ propagated: Array<{ source, target }>, discovered_zone_links: Array }>}
 */
export async function createDiscovery(gameId, { source_id, target_id, link_id }) {
    const body = { source_id, target_id };
    if (link_id) {
        body.link_id = link_id;
    }
    return apiFetch(`/api/games/${gameId}/discoveries`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

/**
 * Undiscover a zone (and cascade to unreachable zones).
 * @param {string} gameId - Game UUID
 * @param {string} zoneId - Zone key to undiscover
 * @returns {Promise<{ removed: string[], discovered_zone_links: Array }>}
 */
export async function undiscoverZone(gameId, zoneId) {
    return apiFetch(`/api/games/${gameId}/undiscoveries`, {
        method: 'POST',
        body: JSON.stringify({ zone_id: zoneId }),
    });
}

// =============================================================================
// Version API
// =============================================================================

/**
 * Get the last seen server version.
 * @returns {string|null} Server version or null if no API call made yet
 */
export function getLastServerVersion() {
    return lastServerVersion;
}

/**
 * Get the client version.
 * @returns {string} Client version
 */
export function getClientVersion() {
    return VERSION;
}

/**
 * Check version compatibility between client and server.
 * @returns {{ compatible: boolean, updateAvailable: boolean, serverVersion: string|null }}
 */
export function checkVersionCompatibility() {
    if (!lastServerVersion) {
        return { compatible: true, updateAvailable: false, serverVersion: null };
    }

    const [clientMajor] = VERSION.split('.').map(Number);
    const [serverMajor] = lastServerVersion.split('.').map(Number);

    if (clientMajor !== serverMajor) {
        return { compatible: false, updateAvailable: false, serverVersion: lastServerVersion };
    }

    // Same major - check if server is newer
    const updateAvailable = lastServerVersion > VERSION;
    return { compatible: true, updateAvailable, serverVersion: lastServerVersion };
}

export default {
    parseSpoilerLog,
    transformZonesFromApi,
    transformLinksFromApi,
    transformZonesToApi,
    transformLinksToApi,
    createGame,
    getGame,
    getMyGames,
    deleteGame,
    updateGame,
    getUser,
    getUserGames,
    regenerateModToken,
    createDiscovery,
    undiscoverZone,
    getLastServerVersion,
    getClientVersion,
    checkVersionCompatibility,
};
