/**
 * REST API client for the fog-tracker backend.
 */

import { getAuthHeaders } from './auth.js';

const DEFAULT_TIMEOUT_MS = 30000;

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
                ...getAuthHeaders(),
                ...options.headers,
            },
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
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
 * @param {Array} zones - Zones from API (snake_case)
 * @returns {Array} Zones in frontend format (camelCase)
 */
export function transformZonesFromApi(zones) {
    return zones.map((zone, index) => ({
        id: zone.name,
        uuid: zone.id,
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
        source: link.source,
        sourceId: link.source_id || null,
        sourceKey: link.source_key || null,
        target: link.target,
        targetId: link.target_id || null,
        targetKey: link.target_key || null,
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
        id: node.uuid || node.id,
        name: node.id,
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
            source: sourceId,
            source_id: link.sourceId || null,
            source_key: link.sourceKey || null,
            target: targetId,
            target_id: link.targetId || null,
            target_key: link.targetKey || null,
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
 * @returns {Promise<{ username: string, displayName: string }>}
 */
export async function getUser(username) {
    const data = await apiFetch(`/api/users/${username}`);
    return {
        username: data.username,
        displayName: data.display_name || data.username,
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
 * @param {Object} data - { source, target, link_id? }
 * @returns {Promise<{ propagated: Array<{ source, target }>, discovered_zone_links: Array }>}
 */
export async function createDiscovery(gameId, { source, target, link_id }) {
    const body = { source, target };
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
 * @param {string} zone - Zone ID to undiscover
 * @returns {Promise<{ removed: string[], discovered_zone_links: Array }>}
 */
export async function undiscoverZone(gameId, zone) {
    return apiFetch(`/api/games/${gameId}/undiscoveries`, {
        method: 'POST',
        body: JSON.stringify({ zone }),
    });
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
};
