/**
 * Dashboard page - List user's games, create new games.
 */

import * as Auth from '../auth.js';
import * as Api from '../api.js';
import { navigate } from '../router.js';
import { SpoilerLogParser } from '../parser.js';
import * as Toast from '../toast.js';

// Module state
let currentUser = null;

let parsedData = null;

/**
 * Show the dashboard page.
 */
export function show() {
  document.querySelectorAll('.page').forEach((p) => p.classList.add('hidden'));
  document.getElementById('dashboard-page').classList.remove('hidden');
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
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) handleFileSelect(file);
  });

  // Create game button
  document.getElementById('create-game-btn').addEventListener('click', createGame);

  // Cancel/close new game modal buttons
  document.getElementById('cancel-new-game-btn').addEventListener('click', closeNewGameModal);
  document.getElementById('close-new-game-modal').addEventListener('click', closeNewGameModal);
  document.getElementById('new-game-modal').addEventListener('click', (e) => {
    if (e.target.id === 'new-game-modal') closeNewGameModal();
  });

  // Mod config modal
  document.getElementById('close-mod-config-modal').addEventListener('click', closeModConfigModal);
  document.getElementById('close-mod-config-modal-btn').addEventListener('click', closeModConfigModal);
  document.getElementById('copy-mod-config-btn').addEventListener('click', copyModConfig);
  document.getElementById('mod-config-modal').addEventListener('click', (e) => {
    if (e.target.id === 'mod-config-modal') closeModConfigModal();
  });
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
    const result = SpoilerLogParser.parse(text);

    if (!result || !result.metadata?.seed) {
      throw new Error('Invalid spoiler log format');
    }

    // Store in format expected by createGame
    parsedData = {
      seed: result.metadata.seed,
      graphData: {
        nodes: result.nodes,
        links: result.links,
      },
    };

    // Show the new game modal
    document.getElementById('new-game-seed').textContent = parsedData.seed;
    document.getElementById('new-game-label').value = '';
    document.getElementById('new-game-modal').classList.remove('hidden');
    document.getElementById('new-game-label').focus();
  } catch (e) {
    errorEl.textContent = e.message || 'Failed to parse spoiler log';
    errorEl.classList.remove('hidden');
    document.getElementById('new-game-modal').classList.remove('hidden');
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

  // Convert graph data to zone_pairs format
  const zonePairs = parsedData.graphData.links.map((link) => ({
    source: typeof link.source === 'object' ? link.source.id : link.source,
    destination: typeof link.target === 'object' ? link.target.id : link.target,
    type: link.type || 'random',
    source_details: link.sourceDetails || null,
    target_details: link.targetDetails || null,
    is_inherently_one_way: link.isInherentlyOneWay || false,
  }));

  // Convert graph data to zones format (node metadata)
  const zones = parsedData.graphData.nodes.map((node) => ({
    id: node.id,
    is_boss: node.isBoss || false,
    scaling: node.scaling || null,
  }));

  createBtn.disabled = true;
  createBtn.textContent = 'Creating...';

  try {
    const response = await Api.createGame({
      seed: parsedData.seed,
      runId: `web_${Date.now()}`,
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
    games.forEach((game) => {
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
  card.addEventListener('dragover', (e) => {
    e.preventDefault();
    card.classList.add('drag-over');
  });

  card.addEventListener('dragleave', () => {
    card.classList.remove('drag-over');
  });

  card.addEventListener('drop', (e) => {
    e.preventDefault();
    card.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  });

  return card;
}

/**
 * Create a game card element.
 */
function createGameCard(game) {
  const card = document.createElement('div');
  card.className = 'game-card';
  card.dataset.gameId = game.id;

  const percent = game.total_zones > 0 ? Math.round((game.discovery_count / game.total_zones) * 100) : 0;

  const updatedDate = new Date(game.updated_at).toLocaleDateString();

  // Mod connection indicator (green dot if connected)
  const modIndicator = game.mod_connected
    ? '<span class="mod-indicator mod-connected" title="Mod connected"></span>'
    : '';

  card.innerHTML = `
    <div class="game-card-header">
      <span class="game-label">${escapeHtml(game.label || 'Untitled')}${modIndicator}</span>
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
  card.querySelector('.game-delete-btn').addEventListener('click', async (e) => {
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
// MOD CONFIG MODAL
// =============================================================================

/**
 * Generate the mod config TOML content for a game.
 */
function generateModConfig(gameId) {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const serverUrl = `${wsProtocol}//${window.location.host}`;
  const modToken = currentUser?.modToken || '<your_mod_token>';

  return `[server]
enabled = true
url = "${serverUrl}"
mod_token = "${modToken}"
game_id = "${gameId}"
auto_reconnect = true`;
}

/**
 * Show the mod config modal for a specific game.
 */
function showModConfigModal(gameId) {
  const modal = document.getElementById('mod-config-modal');
  const content = document.getElementById('mod-config-content');

  content.textContent = generateModConfig(gameId);
  modal.classList.remove('hidden');
}

/**
 * Close the mod config modal.
 */
function closeModConfigModal() {
  document.getElementById('mod-config-modal').classList.add('hidden');
}

/**
 * Copy the mod config to clipboard.
 */
async function copyModConfig() {
  const content = document.getElementById('mod-config-content').textContent;

  try {
    await navigator.clipboard.writeText(content);
    Toast.show('Config copied to clipboard');
  } catch (e) {
    // Fallback
    const textarea = document.createElement('textarea');
    textarea.value = content;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    Toast.show('Config copied to clipboard');
  }
}

/**
 * Route handler for dashboard page.
 */
export async function handleRoute() {
  // Ensure user is loaded
  let user = Auth.getUser();
  if (!user) {
    user = await Auth.fetchUser();
  }

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
      document.querySelectorAll('.page').forEach((p) => p.classList.add('hidden'));
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
  const defaultAvatar =
    'data:image/svg+xml,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%237a6d55"><circle cx="12" cy="8" r="4"/><path d="M12 14c-6 0-8 3-8 6v1h16v-1c0-3-2-6-8-6z"/></svg>'
    );
  avatarEl.src = user.avatarUrl || defaultAvatar;
  avatarEl.onerror = () => {
    avatarEl.src = defaultAvatar;
  };

  show();
  await loadGames();
}

export default {
  show,
  init,
  handleRoute,
};
