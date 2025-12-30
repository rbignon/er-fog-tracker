// ============================================================
// MAIN - Application entry point and orchestration
// ============================================================

import * as Router from './router.js';
import * as Auth from './auth.js';
import * as State from './state.js';
import * as UI from './ui.js';
import * as Graph from './graph.js';
import * as Sync from './sync/index.js';
import * as Toast from './toast.js';
import { checkVersionCompatibility } from './api.js';

// Pages
import * as LandingPage from './pages/landing.js';
import * as DashboardPage from './pages/dashboard.js';
import * as ViewerListPage from './pages/viewer-list.js';
import * as HelpPage from './pages/help.js';

// Track if version notification was already shown
let versionNotificationShown = false;

// ============================================================
// VERSION CHECK
// ============================================================

/**
 * Check version compatibility after an API call and show notification if needed.
 * Only shows notification once per session.
 */
function checkAndNotifyVersion() {
    if (versionNotificationShown) return;

    const { compatible, updateAvailable, serverVersion } = checkVersionCompatibility();

    if (!compatible && serverVersion) {
        versionNotificationShown = true;
        Toast.showVersionIncompatible(serverVersion);
    } else if (updateAvailable && serverVersion) {
        versionNotificationShown = true;
        Toast.showUpdateAvailable(serverVersion);
    }
}

// ============================================================
// HELPERS
// ============================================================

/**
 * Show or hide the graph loading overlay.
 * @param {boolean} show - Whether to show the loading overlay
 */
function setGraphLoading(show) {
    const loadingEl = document.getElementById('graph-loading');
    if (loadingEl) {
        loadingEl.classList.toggle('hidden', !show);
    }
}

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
    document.querySelectorAll('.page').forEach(p => {
        p.classList.add('hidden');
        p.classList.remove('visible');
    });
    document.getElementById('main-ui').classList.remove('hidden');
    document.getElementById('main-ui').classList.add('visible');
    document.body.classList.add('graph-mode');

    // Set navigation links to dashboard
    setNavigationLinks('/dashboard', 'Dashboard');

    // Hide "Load New File" button (game already loaded from server)
    document.getElementById('new-file-btn').classList.add('hidden');

    // Show Stream button and Mod status indicator (host can share OBS URL)
    document.getElementById('stream-btn').classList.remove('hidden');
    document.getElementById('mod-status').classList.remove('hidden');

    // Configure for online mode
    State.setBackendMode('online');
    State.setGameId(gameId);

    // Load game from server and initialize
    await initPlayMode(gameId);

    // Return cleanup function
    return () => {
        Sync.disconnect();
        State.setGameId(null);
        document.body.classList.remove('graph-mode');
    };
}

/**
 * Handler for /watch/:username/:gameId route (viewer mode).
 */
async function handleViewerRoute({ params, query }) {
    const { username, gameId } = params;
    const isOverlay = query.overlay === 'true';

    // Show main UI
    document.querySelectorAll('.page').forEach(p => {
        p.classList.add('hidden');
        p.classList.remove('visible');
    });
    document.getElementById('main-ui').classList.remove('hidden');
    document.getElementById('main-ui').classList.add('visible');
    document.body.classList.add('graph-mode');

    // Configure for viewer mode
    State.setBackendMode('online');
    State.setGameId(gameId);
    State.setIsViewer(true);
    State.setIsOverlayMode(isOverlay);

    if (isOverlay) {
        // OBS Overlay mode: transparent background, no UI
        // Note: #header is hidden via CSS (body.overlay-mode #header { display: none })
        document.body.classList.add('overlay-mode');

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
        document.getElementById('mod-status').classList.add('hidden');

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
        document.body.classList.remove('graph-mode');
        document.body.classList.remove('overlay-mode');
        document.body.classList.remove('viewer-interactive');
    };
}

/**
 * Handler for offline mode (/?offline=true after file upload).
 */
function handleOfflineGraphLoaded() {
    // Show main UI
    document.querySelectorAll('.page').forEach(p => {
        p.classList.add('hidden');
        p.classList.remove('visible');
    });
    document.getElementById('main-ui').classList.remove('hidden');
    document.getElementById('main-ui').classList.add('visible');
    document.body.classList.add('graph-mode');

    // Set navigation to offline home (upload screen)
    setNavigationLinks('/?offline=true', null);

    // Show "Load New File" button
    document.getElementById('new-file-btn').classList.remove('hidden');

    // Hide stream and mod status (no streaming/mod in offline mode)
    document.getElementById('stream-btn').classList.add('hidden');
    document.getElementById('mod-status').classList.add('hidden');

    // Configure for offline mode
    State.setBackendMode('offline');

    // Hide loading spinner (graph is already loaded from file)
    setGraphLoading(false);
}

// ============================================================
// MODE INITIALIZATION
// ============================================================

/**
 * Initialize play mode (host) - load game from server.
 */
async function initPlayMode(gameId) {
    setGraphLoading(true);
    try {
        const { getGame } = await import('./api.js');
        const game = await getGame(gameId);

        // Check version compatibility after API call
        checkAndNotifyVersion();

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

        // Hide loading after render starts (graph will appear shortly)
        setGraphLoading(false);
    } catch (e) {
        setGraphLoading(false);
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
    setGraphLoading(true);
    try {
        const { getGame } = await import('./api.js');
        const game = await getGame(gameId);

        // Check version compatibility after API call
        checkAndNotifyVersion();

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

        // Hide loading after render starts (graph will appear shortly)
        setGraphLoading(false);
    } catch (e) {
        setGraphLoading(false);
        console.error('Failed to load game:', e);
        const Toast = await import('./toast.js');
        Toast.error(`Failed to load game: ${e.message}`);
    }
}

/**
 * Convert server game data to client graph format.
 */
async function convertServerDataToGraph(game) {
    const { transformLinksFromApi } = await import('./api.js');

    // Build zone metadata map if available
    // Note: zones have UUID id but links use zone names, so key by name
    const zoneMetadata = new Map();
    if (game.zones) {
        for (const zone of game.zones) {
            if (zone.name) {
                zoneMetadata.set(zone.name, {
                    uuid: zone.id,
                    isBoss: zone.is_boss || false,
                    scaling: zone.scaling || null,
                });
            }
        }
    }

    // Transform links using centralized function (required_item comes from API)
    const links = transformLinksFromApi(game.zone_links);

    // Build nodes from links (zones might not include all nodes)
    const nodes = new Map();
    for (const link of links) {
        if (!nodes.has(link.source)) {
            const meta = zoneMetadata.get(link.source) || {};
            nodes.set(link.source, {
                id: link.source,
                uuid: meta.uuid || null,
                isBoss: meta.isBoss || false,
                scaling: meta.scaling || null,
            });
        }
        if (!nodes.has(link.target)) {
            const meta = zoneMetadata.get(link.target) || {};
            nodes.set(link.target, {
                id: link.target,
                uuid: meta.uuid || null,
                isBoss: meta.isBoss || false,
                scaling: meta.scaling || null,
            });
        }
    }

    return {
        nodes: Array.from(nodes.values()),
        links,
        metadata: {
            seed: game.seed,
            label: game.label,
            discoveryCount: game.discovery_count,
            totalZones: game.total_zones,
        },
    };
}

/**
 * Load exploration state from server response.
 * Server sends links with {zone_link_id} format - we resolve source/target via linkIndex.
 */
function loadExplorationFromServer(game) {
    // Build discovered nodes from discovered zone links
    const discovered = new Set(['Chapel of Anticipation']);
    const discoveredLinks = new Set();

    // Use linkIndex (already built by setGraphData) to resolve zone_link_id → source/target
    const linkIndex = State.getLinkIndex();

    for (const link of game.discovered_zone_links || []) {
        const linkId = link.zone_link_id || link.link_id;
        if (linkId) {
            discoveredLinks.add(linkId);

            // Resolve source/target from linkIndex
            const linkData = linkIndex?.byId.get(linkId);
            if (linkData) {
                const { sourceId, targetId } = State.getLinkEndpoints(linkData);
                discovered.add(sourceId);
                discovered.add(targetId);
            }
        }
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
    HelpPage.init();

    // Initialize UI event listeners (for graph UI)
    UI.initUI();

    // Initialize stream modal (OBS URL generator)
    Sync.initStreamUI();

    // Subscribe to graph render events
    State.subscribe('graphNeedsRender', ({ preservePositions, centerOnNodeId, showTooltipForNodeId }) => {
        Graph.renderGraph(preservePositions);

        // Center on discovered node after render stabilizes
        // Only for host - viewers control their own viewport
        if (centerOnNodeId && !State.isViewerMode()) {
            setTimeout(() => {
                Graph.centerOnNode(centerOnNodeId);
            }, 300);
        }

        // Show tooltip for newly discovered node (host only)
        if (showTooltipForNodeId && !State.isViewerMode()) {
            setTimeout(() => {
                State.emit('showTooltipForNode', { nodeId: showTooltipForNodeId });
            }, 350); // After centering animation starts
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
    Router.addRoute('/help', HelpPage.handleRoute);

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
