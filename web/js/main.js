// ============================================================
// MAIN - Application entry point and orchestration
// ============================================================

import * as Router from './router.js';
import * as Auth from './auth.js';
import * as State from './state.js';
import * as UI from './ui.js';
import * as Graph from './graph.js';
import * as Sync from './sync.js';

// Pages
import * as LandingPage from './pages/landing.js';
import * as DashboardPage from './pages/dashboard.js';
import * as ViewerListPage from './pages/viewer-list.js';

// ============================================================
// HELPERS
// ============================================================

/**
 * Set the navigation links (title and back link) to the same destination.
 * @param {string} href - The URL to navigate to
 * @param {string|null} backText - Text for back link, or null to hide it
 */
function setNavigationLinks(href, backText = null) {
  const titleLink = document.getElementById('header-title-link');
  const backLink = document.getElementById('header-back-link');

  titleLink.href = href;

  if (backText) {
    backLink.href = href;
    backLink.textContent = `← ${backText}`;
    backLink.classList.remove('hidden');
  } else {
    backLink.classList.add('hidden');
  }
}

// ============================================================
// PAGE HANDLERS
// ============================================================

/**
 * Handler for /play/:gameId route (host mode).
 */
async function handlePlayRoute({ params, query }) {
  const { gameId } = params;

  // Show main UI
  document.querySelectorAll('.page').forEach((p) => {
    p.classList.add('hidden');
    p.classList.remove('visible');
  });
  document.getElementById('main-ui').classList.remove('hidden');
  document.getElementById('main-ui').classList.add('visible');

  // Set navigation links to dashboard
  setNavigationLinks('/dashboard', 'Dashboard');

  // Hide "Load New File" button (game already loaded from server)
  document.getElementById('new-file-btn').classList.add('hidden');

  // Show Stream and Mod buttons (host can share OBS URL and configure mod)
  document.getElementById('stream-btn').classList.remove('hidden');
  document.getElementById('mod-btn').classList.remove('hidden');

  // Configure for online mode
  State.setBackendMode('online');
  State.setGameId(gameId);

  // Load game from server and initialize
  await initPlayMode(gameId);

  // Return cleanup function
  return () => {
    Sync.disconnect();
    State.setGameId(null);
  };
}

/**
 * Handler for /watch/:username/:gameId route (viewer mode).
 */
async function handleViewerRoute({ params, query }) {
  const { username, gameId } = params;
  const isOverlay = query.overlay === 'true';

  // Show main UI
  document.querySelectorAll('.page').forEach((p) => {
    p.classList.add('hidden');
    p.classList.remove('visible');
  });
  document.getElementById('main-ui').classList.remove('hidden');
  document.getElementById('main-ui').classList.add('visible');

  // Configure for viewer mode
  State.setBackendMode('online');
  State.setGameId(gameId);
  State.setIsViewer(true);
  State.setIsOverlayMode(isOverlay);

  if (isOverlay) {
    // OBS Overlay mode: transparent background, no UI
    document.body.classList.add('overlay-mode');
    document.getElementById('header-back-link').classList.add('hidden');
    document.getElementById('new-file-btn').classList.add('hidden');
    document.getElementById('stream-btn').classList.add('hidden');
    document.getElementById('mod-btn').classList.add('hidden');
    document.getElementById('controls').classList.add('hidden');
    document.getElementById('seed-info').classList.add('hidden');

    // Setup viewer counter from query params
    const counterPosition = query.counter || 'br';
    const counterSize = query.size || 'md';
    setupViewerCounter(counterPosition, counterSize);
  } else {
    // Interactive viewer mode: show UI but read-only
    document.body.classList.remove('overlay-mode');
    document.body.classList.add('viewer-interactive');
    setNavigationLinks(`/watch/${username}`, username);

    // Hide host-only controls
    document.getElementById('new-file-btn').classList.add('hidden');
    document.getElementById('stream-btn').classList.add('hidden');
    document.getElementById('mod-btn').classList.add('hidden');

    // Hide viewer counter (only for overlay)
    document.getElementById('viewer-discovery-counter')?.classList.add('hidden');
  }

  // Load game and connect as viewer
  await initViewerMode(gameId);

  // Return cleanup function
  return () => {
    Sync.disconnect();
    State.setGameId(null);
    State.setIsViewer(false);
    State.setIsOverlayMode(false);
    document.body.classList.remove('overlay-mode');
    document.body.classList.remove('viewer-interactive');
  };
}

/**
 * Handler for offline mode (/?offline=true after file upload).
 */
function handleOfflineGraphLoaded() {
  // Show main UI
  document.querySelectorAll('.page').forEach((p) => {
    p.classList.add('hidden');
    p.classList.remove('visible');
  });
  document.getElementById('main-ui').classList.remove('hidden');
  document.getElementById('main-ui').classList.add('visible');

  // Set navigation to home (no back link text in offline)
  setNavigationLinks('/?offline=true', null);

  // Show "Load New File" button
  document.getElementById('new-file-btn').classList.remove('hidden');

  // Hide stream and mod buttons (no streaming/mod in offline mode)
  document.getElementById('stream-btn').classList.add('hidden');
  document.getElementById('mod-btn').classList.add('hidden');

  // Configure for offline mode
  State.setBackendMode('offline');
}

// ============================================================
// MODE INITIALIZATION
// ============================================================

/**
 * Initialize play mode (host) - load game from server.
 */
async function initPlayMode(gameId) {
  try {
    const { getGame } = await import('./api.js');
    const game = await getGame(gameId);

    // Convert server data to graph format
    const graphData = await convertServerDataToGraph(game);

    // Set graph data
    State.setSeed(game.seed);
    State.setGraphData(graphData);

    // Load exploration state from server
    loadExplorationFromServer(game);

    // Initialize WebSocket connection as host
    await Sync.connectAsHost(gameId);

    // Trigger initial render - only preserve positions if we have some saved
    const hasPositions = State.getNodePositions().size > 0;
    State.emit('graphNeedsRender', { preservePositions: hasPositions });
  } catch (e) {
    console.error('Failed to load game:', e);
    const Toast = await import('./toast.js');
    Toast.error(`Failed to load game: ${e.message}`);
    Router.navigate('/dashboard', { replace: true });
  }
}

/**
 * Initialize viewer mode - load game and connect as viewer.
 */
async function initViewerMode(gameId) {
  try {
    const { getGame } = await import('./api.js');
    const game = await getGame(gameId);

    // Convert server data to graph format
    const graphData = await convertServerDataToGraph(game);

    // Set graph data
    State.setSeed(game.seed);
    State.setGraphData(graphData);

    // Load exploration state from server
    loadExplorationFromServer(game);

    // Connect as viewer
    await Sync.connectAsViewer(gameId);

    // Trigger initial render - only preserve positions if we have some saved
    const hasPositions = State.getNodePositions().size > 0;
    State.emit('graphNeedsRender', { preservePositions: hasPositions });
  } catch (e) {
    console.error('Failed to load game:', e);
    const Toast = await import('./toast.js');
    Toast.error(`Failed to load game: ${e.message}`);
  }
}

/**
 * Convert server game data to client graph format.
 */
async function convertServerDataToGraph(game) {
  const { extractRequiredItemFromDescription } = await import('./parser.js');

  // Build zone metadata map if available
  const zoneMetadata = new Map();
  if (game.zones) {
    for (const zone of game.zones) {
      zoneMetadata.set(zone.id, {
        isBoss: zone.is_boss || false,
        scaling: zone.scaling || null,
      });
    }
  }

  const nodes = new Map();
  const links = [];

  for (const pair of game.zone_pairs) {
    // Add nodes with metadata if available
    if (!nodes.has(pair.source)) {
      const meta = zoneMetadata.get(pair.source) || {};
      nodes.set(pair.source, {
        id: pair.source,
        isBoss: meta.isBoss || false,
        scaling: meta.scaling || null,
      });
    }
    if (!nodes.has(pair.destination)) {
      const meta = zoneMetadata.get(pair.destination) || {};
      nodes.set(pair.destination, {
        id: pair.destination,
        isBoss: meta.isBoss || false,
        scaling: meta.scaling || null,
      });
    }

    // Check for required key items
    const requiredItemFrom = extractRequiredItemFromDescription(
      pair.source_details,
      pair.target_details
    );

    // Add link
    links.push({
      source: pair.source,
      target: pair.destination,
      type: pair.type,
      sourceDetails: pair.source_details,
      targetDetails: pair.target_details,
      requiredItemFrom,
    });
  }

  return {
    nodes: Array.from(nodes.values()),
    links,
    metadata: {
      seed: game.seed,
      label: game.label,
    },
  };
}

/**
 * Load exploration state from server response.
 */
function loadExplorationFromServer(game) {
  // Build discovered nodes from discovered links
  const discovered = new Set(['Chapel of Anticipation']);
  const discoveredLinks = new Set();

  for (const link of game.discovered_links || []) {
    discovered.add(link.source);
    discovered.add(link.target);
    discoveredLinks.add(`${link.source}|${link.target}`);
  }

  // Build tags map
  const tags = new Map();
  for (const [zone, zoneTags] of Object.entries(game.tags || {})) {
    tags.set(zone, zoneTags);
  }

  // Set exploration state
  State.setExplorationState({
    discovered,
    discoveredLinks,
    tags,
  });

  // Load node positions
  if (game.node_positions) {
    const positions = new Map();
    for (const [nodeId, pos] of Object.entries(game.node_positions)) {
      positions.set(nodeId, { x: pos.x, y: pos.y });
    }
    State.setNodePositions(positions);
  }
}

/**
 * Setup viewer discovery counter.
 */
function setupViewerCounter(position, size) {
  const counter = document.getElementById('viewer-discovery-counter');

  if (position === 'off') {
    counter.classList.add('hidden');
    return;
  }

  counter.classList.remove('hidden');

  // Remove existing position classes
  counter.className = counter.className.replace(/counter-pos-\w+/g, '').trim();
  counter.className = counter.className.replace(/counter-size-\w+/g, '').trim();

  // Add new classes
  counter.classList.add(`counter-pos-${position}`);
  counter.classList.add(`counter-size-${size}`);
}

// ============================================================
// INITIALIZATION
// ============================================================

async function init() {
  console.log('Initializing application...');

  // Initialize auth (check for token in URL, load cached user)
  await Auth.init();

  // Initialize page modules
  LandingPage.init();
  DashboardPage.init();
  ViewerListPage.init();

  // Initialize UI event listeners (for graph UI)
  UI.initUI();

  // Initialize stream modal (OBS URL generator)
  Sync.initStreamUI();

  // Initialize mod modal (configuration)
  Sync.initModUI();

  // Subscribe to graph render events
  State.subscribe('graphNeedsRender', ({ preservePositions, centerOnNodeId }) => {
    Graph.renderGraph(preservePositions);

    // Center on discovered node after render stabilizes
    if (centerOnNodeId) {
      setTimeout(() => {
        Graph.centerOnNode(centerOnNodeId);
      }, 300);
    }
  });

  // Listen for offline mode file loaded
  State.subscribe('graphDataChanged', () => {
    if (State.getBackendMode() === 'offline' && State.getGraphData()) {
      handleOfflineGraphLoaded();
    }
  });

  // Register routes
  Router.addRoute('/', LandingPage.handleRoute);
  Router.addRoute('/dashboard', DashboardPage.handleRoute, { auth: true });
  Router.addRoute('/play/:gameId', handlePlayRoute, { auth: true });
  Router.addRoute('/watch/:username', ViewerListPage.handleRoute);
  Router.addRoute('/watch/:username/:gameId', handleViewerRoute);

  // Initialize router (handles current URL)
  Router.init();

  console.log('Application initialized');
}

// ============================================================
// START APPLICATION
// ============================================================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// Export for use by other modules
export { handleOfflineGraphLoaded };
