/**
 * Viewer list page - Public list of a user's games.
 * Route: /watch/:username
 */

import * as Api from '../api.js';

/**
 * Show the user games page.
 */
export function show() {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('user-games-page').classList.remove('hidden');
}

/**
 * Initialize page (no persistent handlers needed).
 */
export function init() {
    // Nothing to initialize
}

/**
 * Load and render the user's games.
 */
async function loadUserGames(username) {
    const listEl = document.getElementById('user-games-list');
    const emptyEl = document.getElementById('user-games-empty');
    const loadingEl = document.getElementById('user-games-loading');
    const errorEl = document.getElementById('user-games-error');
    const displayNameEl = document.getElementById('user-games-displayname');
    const avatarEl = document.getElementById('user-games-avatar');
    const twitchLinkEl = document.getElementById('user-games-twitch-link');

    listEl.innerHTML = '';
    emptyEl.classList.add('hidden');
    errorEl.classList.add('hidden');
    loadingEl.classList.remove('hidden');

    try {
        // Fetch user info
        const user = await Api.getUser(username);
        displayNameEl.textContent = user.displayName;

        // Set avatar with fallback
        const defaultAvatar = `data:image/svg+xml,${encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%237a6d55"><circle cx="12" cy="8" r="4"/><path d="M12 14c-6 0-8 3-8 6v1h16v-1c0-3-2-6-8-6z"/></svg>'
        )}`;
        avatarEl.src = user.avatarUrl || defaultAvatar;
        avatarEl.onerror = () => {
            avatarEl.src = defaultAvatar;
        };

        // Set Twitch link
        twitchLinkEl.href = `https://twitch.tv/${user.username}`;

        // Fetch games
        const { games } = await Api.getUserGames(username);

        loadingEl.classList.add('hidden');

        if (games.length === 0) {
            emptyEl.classList.remove('hidden');
            return;
        }

        games.forEach(game => {
            listEl.appendChild(createGameCard(game, username));
        });
    } catch (e) {
        loadingEl.classList.add('hidden');

        if (e.status === 404) {
            errorEl.textContent = 'User not found';
        } else {
            errorEl.textContent = e.detail || e.message || 'Failed to load games';
        }
        errorEl.classList.remove('hidden');
    }
}

/**
 * Format a date using browser locale.
 */
function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

/**
 * Get display label for a game.
 */
function getGameLabel(game) {
    if (game.label) {
        return game.label;
    }
    const createdDate = formatDate(game.created_at);
    return `Seed ${game.seed} (${createdDate})`;
}

/**
 * Create a game card element for viewer list.
 */
function createGameCard(game, username) {
    const card = document.createElement('div');
    card.className = 'game-card game-card-viewer';

    const percent = game.total_zones > 0 ? Math.round((game.discovery_count / game.total_zones) * 100) : 0;

    const updatedDate = formatDate(game.updated_at);

    card.innerHTML = `
    <div class="game-card-header">
      <span class="game-label">${escapeHtml(getGameLabel(game))}</span>
    </div>
    <div class="game-card-body">
      <div class="game-seed">Seed: ${game.seed}</div>
      <div class="game-progress">
        <span class="progress-text">${game.discovery_count}/${game.total_zones}</span>
        <span class="progress-percent">(${percent}%)</span>
      </div>
      <div class="game-progress-bar">
        <div class="game-progress-fill" style="width: ${percent}%"></div>
      </div>
      <div class="game-updated">Updated: ${updatedDate}</div>
    </div>
    <div class="game-card-footer">
      <a href="/watch/${encodeURIComponent(username)}/${game.id}" class="btn-primary btn-small">Watch</a>
    </div>
  `;

    return card;
}

/**
 * Escape HTML to prevent XSS.
 */
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Route handler for user games page.
 */
export async function handleRoute({ params }) {
    const { username } = params;

    show();
    await loadUserGames(username);
}

export default {
    show,
    init,
    handleRoute,
};
