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

  // File upload drop zone
  const dropZone = document.getElementById('new-game-drop-zone');
  const fileInput = document.getElementById('new-game-file-input');

  dropZone.addEventListener('click', () => fileInput.click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  });

  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) handleFileSelect(file);
  });

  // Create game button
  document.getElementById('create-game-btn').addEventListener('click', createGame);

  // Cancel button
  document.getElementById('cancel-new-game-btn').addEventListener('click', () => {
    resetNewGameForm();
  });

  // Mod token buttons
  document.getElementById('toggle-mod-token-btn').addEventListener('click', toggleModTokenVisibility);
  document.getElementById('copy-mod-token-btn').addEventListener('click', copyModToken);
  document.getElementById('regenerate-mod-token-btn').addEventListener('click', regenerateModToken);
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

    // Show the form
    document.getElementById('new-game-drop-zone').classList.add('hidden');
    document.getElementById('new-game-form').classList.remove('hidden');
    document.getElementById('new-game-seed').textContent = parsedData.seed;
    document.getElementById('new-game-label').value = '';
    document.getElementById('new-game-label').focus();
  } catch (e) {
    errorEl.textContent = e.message || 'Failed to parse spoiler log';
    errorEl.classList.remove('hidden');
  }
}

/**
 * Reset the new game form.
 */
function resetNewGameForm() {
  parsedData = null;
  document.getElementById('new-game-drop-zone').classList.remove('hidden');
  document.getElementById('new-game-form').classList.add('hidden');
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
  }));

  createBtn.disabled = true;
  createBtn.textContent = 'Creating...';

  try {
    const response = await Api.createGame({
      seed: parsedData.seed,
      runId: `web_${Date.now()}`,
      label: label || null,
      zonePairs,
    });

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
    createBtn.disabled = false;
    createBtn.textContent = 'Create Game';
  }
}

/**
 * Load and render the games list.
 */
async function loadGames() {
  const listEl = document.getElementById('games-list');
  const emptyEl = document.getElementById('games-empty');
  const loadingEl = document.getElementById('games-loading');

  listEl.innerHTML = '';
  emptyEl.classList.add('hidden');
  loadingEl.classList.remove('hidden');

  try {
    const { games } = await Api.getMyGames();

    loadingEl.classList.add('hidden');

    if (games.length === 0) {
      emptyEl.classList.remove('hidden');
      return;
    }

    games.forEach((game) => {
      listEl.appendChild(createGameCard(game));
    });
  } catch (e) {
    loadingEl.classList.add('hidden');
    listEl.innerHTML = `<p class="error-message">Failed to load games: ${e.message}</p>`;
  }
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

  card.innerHTML = `
    <div class="game-card-header">
      <span class="game-label">${escapeHtml(game.label || 'Untitled')}</span>
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

      // Check if list is now empty
      if (document.getElementById('games-list').children.length === 0) {
        document.getElementById('games-empty').classList.remove('hidden');
      }
    } catch (e) {
      Toast.error(`Failed to delete: ${e.message}`);
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

/**
 * Update the mod token display.
 */
function updateModTokenDisplay() {
  const input = document.getElementById('mod-token-input');
  if (currentUser?.modToken) {
    input.value = currentUser.modToken;
  } else {
    input.value = '';
  }
}

/**
 * Toggle mod token visibility.
 */
function toggleModTokenVisibility() {
  const input = document.getElementById('mod-token-input');
  const showIcon = document.getElementById('eye-icon-show');
  const hideIcon = document.getElementById('eye-icon-hide');

  if (input.type === 'password') {
    input.type = 'text';
    showIcon.classList.add('hidden');
    hideIcon.classList.remove('hidden');
  } else {
    input.type = 'password';
    showIcon.classList.remove('hidden');
    hideIcon.classList.add('hidden');
  }
}

/**
 * Copy mod token to clipboard.
 */
async function copyModToken() {
  const input = document.getElementById('mod-token-input');
  if (!input.value) return;

  try {
    await navigator.clipboard.writeText(input.value);
    Toast.show('Token copied to clipboard');
  } catch (e) {
    // Fallback for older browsers
    input.select();
    document.execCommand('copy');
    Toast.show('Token copied to clipboard');
  }
}

/**
 * Regenerate mod token.
 */
async function regenerateModToken() {
  const btn = document.getElementById('regenerate-mod-token-btn');
  const originalText = btn.textContent;

  if (!confirm('Are you sure? Any existing mod configuration will need to be updated.')) {
    return;
  }

  btn.disabled = true;
  btn.textContent = '...';

  try {
    const response = await Api.regenerateModToken();
    const newToken = response.mod_token;

    // Update cached user
    currentUser.modToken = newToken;
    Auth.updateCachedUser({ modToken: newToken });

    // Update display
    updateModTokenDisplay();

    Toast.show('Token regenerated');
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

  // Reset new game form
  resetNewGameForm();

  // Display mod token
  updateModTokenDisplay();

  show();
  await loadGames();
}

export default {
  show,
  init,
  handleRoute,
};
