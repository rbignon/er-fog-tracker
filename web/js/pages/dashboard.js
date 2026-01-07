/**
 * Dashboard page - List user's games, create new games.
 */

import * as Auth from '../auth.js';
import * as Api from '../api.js';
import { transformZonesFromApi, transformLinksFromApi, transformZonesToApi, transformLinksToApi } from '../api.js';
import { navigate } from '../router.js';
import * as Toast from '../toast.js';
import { getLinkEndpoints } from '../state.js';

// Module state
let currentUser = null;

let parsedData = null;

/**
 * Show the dashboard page.
 */
export function show() {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('dashboard-page').classList.remove('hidden');
    document.body.classList.remove('graph-mode');
}

/**
 * Initialize dashboard event handlers.
 */
export function init() {
    // Logout button
    document.getElementById('logout-btn').addEventListener('click', () => {
        Auth.logout();
    });

    // File input for new game
    const fileInput = document.getElementById('new-game-file-input');
    fileInput.addEventListener('change', e => {
        const file = e.target.files[0];
        if (file) handleFileSelect(file);
    });

    // Create game button
    document.getElementById('create-game-btn').addEventListener('click', createGame);

    // Cancel/close new game modal buttons
    document.getElementById('cancel-new-game-btn').addEventListener('click', closeNewGameModal);
    document.getElementById('close-new-game-modal').addEventListener('click', closeNewGameModal);
    document.getElementById('new-game-modal').addEventListener('click', e => {
        if (e.target.id === 'new-game-modal') closeNewGameModal();
    });

    // Mod setup banner
    initModSetupBanner();
}

/**
 * Handle file selection for new game.
 */
async function handleFileSelect(file) {
    const errorEl = document.getElementById('new-game-error');
    errorEl.classList.add('hidden');
    errorEl.textContent = '';

    try {
        const text = await file.text();

        // Parse via API
        const apiData = await Api.parseSpoilerLog(text);

        if (!apiData.seed) {
            throw new Error('Invalid spoiler log format');
        }

        // Store in format expected by createGame
        parsedData = {
            seed: apiData.seed,
            graphData: {
                nodes: transformZonesFromApi(apiData.zones),
                links: transformLinksFromApi(apiData.zone_links),
            },
        };

        // Show the new game modal
        document.getElementById('new-game-seed').textContent = parsedData.seed;
        document.getElementById('new-game-label').value = '';
        document.getElementById('new-game-modal').classList.remove('hidden');
        document.getElementById('new-game-label').focus();
    } catch (e) {
        // Show user-friendly error as toast instead of opening modal
        const message = e.detail || e.message || 'Failed to parse spoiler log';
        Toast.error(message);
        // Reset file input so user can try again
        document.getElementById('new-game-file-input').value = '';
    }
}

/**
 * Close the new game modal and reset form.
 */
function closeNewGameModal() {
    parsedData = null;
    document.getElementById('new-game-modal').classList.add('hidden');
    document.getElementById('new-game-file-input').value = '';
    document.getElementById('new-game-error').classList.add('hidden');
}

/**
 * Create a new game from parsed spoiler log.
 */
async function createGame() {
    if (!parsedData) return;

    const label = document.getElementById('new-game-label').value.trim();
    const errorEl = document.getElementById('new-game-error');
    const createBtn = document.getElementById('create-game-btn');

    // Convert graph data to API format
    const zonePairs = transformLinksToApi(parsedData.graphData.links, getLinkEndpoints);
    const zones = transformZonesToApi(parsedData.graphData.nodes);

    createBtn.disabled = true;
    createBtn.textContent = 'Creating...';

    try {
        const response = await Api.createGame({
            seed: parsedData.seed,
            label: label || null,
            zonePairs,
            zones,
        });

        closeNewGameModal();

        if (response.created) {
            Toast.show('Game created!');
        } else {
            Toast.info('Game already exists, opening...');
        }

        // Navigate to play page
        navigate(`/play/${response.game_id}`);
    } catch (e) {
        errorEl.textContent = e.detail || e.message || 'Failed to create game';
        errorEl.classList.remove('hidden');
    } finally {
        createBtn.disabled = false;
        createBtn.textContent = 'Create Game';
    }
}

/**
 * Load and render the games list.
 */
async function loadGames() {
    const listEl = document.getElementById('games-list');
    const loadingEl = document.getElementById('games-loading');

    listEl.innerHTML = '';
    loadingEl.classList.remove('hidden');

    try {
        const { games } = await Api.getMyGames();

        loadingEl.classList.add('hidden');

        // Add game cards
        games.forEach(game => {
            listEl.appendChild(createGameCard(game));
        });

        // Add placeholder card at the end (for creating new game)
        listEl.appendChild(createPlaceholderCard());
    } catch (e) {
        loadingEl.classList.add('hidden');
        listEl.innerHTML = `<p class="error-message">Failed to load games: ${e.message}</p>`;
    }
}

/**
 * Create the placeholder card for adding a new game.
 */
function createPlaceholderCard() {
    const card = document.createElement('div');
    card.className = 'game-card game-card-placeholder';

    card.innerHTML = `
    <div class="placeholder-content">
      <div class="placeholder-icon">+</div>
      <p class="placeholder-text">New Game</p>
      <p class="placeholder-hint">Drop spoiler log or click</p>
    </div>
  `;

    const fileInput = document.getElementById('new-game-file-input');

    // Click to open file dialog
    card.addEventListener('click', () => fileInput.click());

    // Drag and drop
    card.addEventListener('dragover', e => {
        e.preventDefault();
        card.classList.add('drag-over');
    });

    card.addEventListener('dragleave', () => {
        card.classList.remove('drag-over');
    });

    card.addEventListener('drop', e => {
        e.preventDefault();
        card.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) handleFileSelect(file);
    });

    return card;
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
 * Create a game card element.
 */
function createGameCard(game) {
    const card = document.createElement('div');
    card.className = 'game-card';
    card.dataset.gameId = game.id;

    const percent = game.total_zones > 0 ? Math.round((game.discovery_count / game.total_zones) * 100) : 0;

    const updatedDate = formatDate(game.updated_at);

    // Mod connection indicator (green dot if connected)
    const modIndicator = game.mod_connected
        ? '<span class="mod-indicator mod-connected" title="Mod connected"></span>'
        : '';

    card.innerHTML = `
    <div class="game-card-header">
      <span class="game-label">${escapeHtml(getGameLabel(game))}${modIndicator}</span>
      <button class="game-delete-btn" title="Delete game">&times;</button>
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
      <a href="/play/${game.id}" class="btn-primary btn-small">Play</a>
    </div>
  `;

    // Delete button handler
    card.querySelector('.game-delete-btn').addEventListener('click', async e => {
        e.preventDefault();
        e.stopPropagation();

        if (!confirm('Are you sure you want to delete this game?')) return;

        try {
            await Api.deleteGame(game.id);
            card.remove();
            Toast.show('Game deleted');

            // Check if only placeholder remains
            const remainingCards = document.querySelectorAll('#games-list .game-card:not(.game-card-placeholder)');
            if (remainingCards.length === 0) {
                // Reload to show empty state properly
                await loadGames();
            }
        } catch (err) {
            Toast.error(`Failed to delete: ${err.message}`);
        }
    });

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

// =============================================================================
// MOD SETUP BANNER
// =============================================================================

const MOD_SETUP_COLLAPSED_KEY = 'modSetupCollapsed';

/**
 * Initialize the mod setup banner.
 */
function initModSetupBanner() {
    const banner = document.getElementById('mod-setup-banner');
    const toggle = document.getElementById('mod-setup-toggle');

    if (!banner || !toggle) return;

    // Restore collapsed state from localStorage
    const isCollapsed = localStorage.getItem(MOD_SETUP_COLLAPSED_KEY) === 'true';
    if (isCollapsed) {
        banner.classList.add('collapsed');
    }

    // Toggle collapse on header click
    toggle.addEventListener('click', () => {
        banner.classList.toggle('collapsed');
        const collapsed = banner.classList.contains('collapsed');
        localStorage.setItem(MOD_SETUP_COLLAPSED_KEY, collapsed);
    });

    // Copy buttons
    document.querySelectorAll('.btn-copy-field').forEach(btn => {
        btn.addEventListener('click', async () => {
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (input) {
                await navigator.clipboard.writeText(input.value);
                Toast.show('Copied to clipboard');
            }
        });
    });

    // Visibility toggle for token
    document.querySelectorAll('.btn-toggle-visibility').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (input) {
                if (input.type === 'password') {
                    input.type = 'text';
                    btn.textContent = '🙈';
                } else {
                    input.type = 'password';
                    btn.textContent = '👁';
                }
            }
        });
    });

    // Regenerate token button
    const regenerateBtn = document.getElementById('regenerate-token-btn');
    if (regenerateBtn) {
        regenerateBtn.addEventListener('click', regenerateModToken);
    }
}

/**
 * Update the mod setup banner with user credentials.
 */
function updateModSetupCredentials(user) {
    const serverUrlInput = document.getElementById('mod-server-url');
    const tokenInput = document.getElementById('mod-token-field');

    if (serverUrlInput) {
        // Use the current host with HTTP protocol (launcher expects http/https, not ws/wss)
        serverUrlInput.value = `${window.location.protocol}//${window.location.host}`;
    }

    if (tokenInput && user?.modToken) {
        tokenInput.value = user.modToken;
    }
}

/**
 * Regenerate the mod token.
 */
async function regenerateModToken() {
    const btn = document.getElementById('regenerate-token-btn');
    const originalText = btn.textContent;

    try {
        btn.disabled = true;
        btn.textContent = 'Regenerating...';

        const response = await Api.regenerateModToken();

        if (response.mod_token) {
            // Update the token field
            const tokenInput = document.getElementById('mod-token-field');
            if (tokenInput) {
                tokenInput.value = response.mod_token;
            }

            // Update cached user
            if (currentUser) {
                currentUser.modToken = response.mod_token;
            }

            // Update auth cache
            Auth.updateCachedUser({ modToken: response.mod_token });

            Toast.show('Token regenerated successfully');
        }
    } catch (e) {
        Toast.error(`Failed to regenerate token: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

/**
 * Route handler for dashboard page.
 */
export async function handleRoute() {
    // Always verify token with server (not just cached data)
    const user = await Auth.fetchUser();

    if (!user) {
        const error = Auth.getLastFetchError();
        if (error === 'server' || error === 'network') {
            // Server or network error - show error message, don't redirect
            const Toast = await import('../toast.js');
            Toast.error(
                error === 'server'
                    ? 'Server error. Please try again later.'
                    : 'Network error. Please check your connection.'
            );
            // Show landing page but don't auto-redirect to avoid loops
            document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
            document.getElementById('landing-page').classList.remove('hidden');
            Auth.clearLastFetchError();
            return;
        }
        // Auth error or no token - normal redirect
        navigate('/', { replace: true });
        return;
    }

    // Store user for module use
    currentUser = user;

    // Update UI with user info
    document.getElementById('dashboard-username').textContent = user.displayName;

    // Set avatar
    const avatarEl = document.getElementById('dashboard-avatar');
    const defaultAvatar = `data:image/svg+xml,${encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%237a6d55"><circle cx="12" cy="8" r="4"/><path d="M12 14c-6 0-8 3-8 6v1h16v-1c0-3-2-6-8-6z"/></svg>'
    )}`;
    avatarEl.src = user.avatarUrl || defaultAvatar;
    avatarEl.onerror = () => {
        avatarEl.src = defaultAvatar;
    };

    // Update mod setup banner with credentials
    updateModSetupCredentials(user);

    show();
    await loadGames();
}

export default {
    show,
    init,
    handleRoute,
};
