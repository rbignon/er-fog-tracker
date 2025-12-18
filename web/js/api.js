/**
 * REST API client for the fog-vizu backend.
 */

import { getAuthHeaders } from './auth.js';

/**
 * Base fetch wrapper with error handling.
 */
async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options.headers,
    },
  });

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
}

// =============================================================================
// Games API
// =============================================================================

/**
 * Create a new game.
 * @param {Object} data - { seed, runId, label?, zonePairs, zones? }
 * @returns {Promise<{ gameId: string, created: boolean }>}
 */
export async function createGame({ seed, runId, label, zonePairs, zones }) {
  return apiFetch('/api/games', {
    method: 'POST',
    body: JSON.stringify({
      seed,
      run_id: runId,
      label: label || null,
      zone_pairs: zonePairs,
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
 * @returns {Promise<{ propagated: Array<{ source, target }>, discovered_links: Array }>}
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
 * @returns {Promise<{ removed: string[], discovered_links: Array }>}
 */
export async function undiscoverZone(gameId, zone) {
  return apiFetch(`/api/games/${gameId}/undiscoveries`, {
    method: 'POST',
    body: JSON.stringify({ zone }),
  });
}

export default {
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
