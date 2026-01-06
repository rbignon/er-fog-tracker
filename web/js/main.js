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
 * Update the last discovery indicator in the stats panel.
 * @param {string} zoneName - Display name of the last discovered zone
 */
function updateLastDiscoveryIndicator(zoneName) {
    const container = document.getElementById('last-discovery');
    const nameEl = document.getElementById('last-discovery-name');
    if (container && nameEl) {
        nameEl.textContent = zoneName;
        container.classList.remove('hidden');
    }
}

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
 * Fetch and display streamer info (avatar + name) for viewers.
 * @param {string} username - Streamer's username
 */
async function displayStreamerInfo(username) {
    const streamerInfo = document.getElementById('streamer-info');
    const streamerAvatar = document.getElementById('streamer-avatar');
    const streamerName = document.getElementById('streamer-name');
    const streamerTwitchLink = document.getElementById('streamer-twitch-link');

    if (!streamerInfo || !streamerAvatar || !streamerName) return;

    try {
        const { getUser } = await import('./api.js');
        const user = await getUser(username);

        // Set avatar (use placeholder if not available)
        if (user.avatarUrl) {
            streamerAvatar.src = user.avatarUrl;
            streamerAvatar.alt = user.displayName;
        } else {
            streamerAvatar.style.display = 'none';
        }

        // Set name with link to games list
        streamerName.textContent = user.displayName;
        streamerName.href = `/watch/${username}`;

        // Set Twitch link
        if (streamerTwitchLink) {
            streamerTwitchLink.href = `https://twitch.tv/${username}`;
        }

        // Show the streamer info
        streamerInfo.classList.remove('hidden');
    } catch (e) {
        // If we can't fetch user info, just show the username without avatar
        streamerAvatar.style.display = 'none';
        streamerName.textContent = username;
        streamerName.href = `/watch/${username}`;
        if (streamerTwitchLink) {
            streamerTwitchLink.href = `https://twitch.tv/${username}`;
        }
        streamerInfo.classList.remove('hidden');
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

    // Show Stream button, Mod status, and Viewer count indicators (host-only features)
    document.getElementById('stream-btn').classList.remove('hidden');
    document.getElementById('mod-status').classList.remove('hidden');
    document.getElementById('viewer-count').classList.remove('hidden');
    // Hide host status (only for viewers)
    document.getElementById('host-status').classList.add('hidden');

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
        // Don't show back link - streamer info already has clickable name
        setNavigationLinks(`/watch/${username}`, null);

        // Hide host-only controls
        document.getElementById('new-file-btn').classList.add('hidden');
        document.getElementById('stream-btn').classList.add('hidden');
        document.getElementById('mod-status').classList.add('hidden');
        document.getElementById('viewer-count').classList.add('hidden');

        // Show host status indicator for viewers
        document.getElementById('host-status').classList.remove('hidden');

        // Hide viewer counter (only for overlay)
        document.getElementById('viewer-discovery-counter')?.classList.add('hidden');

        // Fetch and display streamer info
        displayStreamerInfo(username);
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
        // Hide streamer info
        document.getElementById('streamer-info')?.classList.add('hidden');
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

    // Hide stream, mod status, viewer count, and host status (no streaming/mod in offline mode)
    document.getElementById('stream-btn').classList.add('hidden');
    document.getElementById('mod-status').classList.add('hidden');
    document.getElementById('viewer-count').classList.add('hidden');
    document.getElementById('host-status').classList.add('hidden');

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

        // Set starting zone before loading exploration state
        if (game.starting_zone_id) {
            State.setStartNodeId(game.starting_zone_id);
        }

        // Convert server data to graph format
        const graphData = await convertServerDataToGraph(game);

        // Set graph data
        State.setSeed(game.seed);
        State.setGraphData(graphData);

        // Load exploration state from server
        loadExplorationFromServer(game);

        // Load game stats if available
        if (game.game_stats) {
            State.setGameStats(game.game_stats);
        }

        // Initialize WebSocket connection as host
        await Sync.connectAsHost(gameId);

        // Trigger initial render - only preserve positions if we have some saved
        const hasPositions = State.getNodePositions().size > 0;
        State.emit('graphNeedsRender', { preservePositions: hasPositions });

        // Update mode buttons (show Reset button if in explorer mode)
        UI.updateModeButtons();

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

        // Set starting zone before loading exploration state
        if (game.starting_zone_id) {
            State.setStartNodeId(game.starting_zone_id);
        }

        // Convert server data to graph format
        const graphData = await convertServerDataToGraph(game);

        // Set graph data
        State.setSeed(game.seed);
        State.setGraphData(graphData);

        // Load exploration state from server
        loadExplorationFromServer(game);

        // Load game stats if available
        if (game.game_stats) {
            State.setGameStats(game.game_stats);
        }

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
    const { transformLinksFromApi, transformZonesFromApi } = await import('./api.js');

    // Transform zones using centralized function (handles dict or array)
    // zones is now a dict keyed by zone_key
    const nodes = game.zones ? transformZonesFromApi(game.zones) : [];

    // Build node map by zone_key for enrichment
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // Transform links using centralized function
    const links = transformLinksFromApi(game.zone_links);

    // Ensure all link endpoints have corresponding nodes
    // (in case zones dict is incomplete)
    for (const link of links) {
        if (!nodeMap.has(link.source)) {
            const node = {
                id: link.source,
                name: link.sourceName || link.source,
                isBoss: false,
                scaling: null,
            };
            nodes.push(node);
            nodeMap.set(link.source, node);
        }
        if (!nodeMap.has(link.target)) {
            const node = {
                id: link.target,
                name: link.targetName || link.target,
                isBoss: false,
                scaling: null,
            };
            nodes.push(node);
            nodeMap.set(link.target, node);
        }
    }

    return {
        nodes,
        links,
        metadata: {
            seed: game.seed,
            label: game.label,
            discoveryCount: game.discovery_count,
            totalZones: game.total_zones,
            startingZoneId: game.starting_zone_id,
        },
    };
}

/**
 * Load exploration state from server response.
 * Server sends links with {zone_link_id} format - we resolve source/target via linkIndex.
 */
function loadExplorationFromServer(game) {
    // Build discovered nodes from discovered zone links
    // Always include starting zone (zone_key)
    const discovered = new Set([State.getStartNodeId()]);
    const discoveredLinks = new Set();

    // Use linkIndex (already built by setGraphData) to resolve zone_link_id → source/target
    const linkIndex = State.getLinkIndex();

    // Find the most recently discovered link to show in "Last discovery"
    let mostRecentLink = null;
    let mostRecentTime = null;

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

            // Track most recent discovery
            if (link.discovered_at) {
                const discoveredTime = new Date(link.discovered_at).getTime();
                if (!mostRecentTime || discoveredTime > mostRecentTime) {
                    mostRecentTime = discoveredTime;
                    mostRecentLink = { linkData, linkId };
                }
            }
        }
    }

    // Update last discovery indicator with most recent zone
    if (mostRecentLink?.linkData) {
        const { targetId } = State.getLinkEndpoints(mostRecentLink.linkData);
        const graphData = State.getGraphData();
        const node = graphData?.nodes?.find(n => n.id === targetId);
        const displayName = node?.name || targetId;
        updateLastDiscoveryIndicator(displayName);
    }

    // Build tags map (keys are now zone_keys)
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

    // Load node positions (keys are now zone_keys)
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
