// ============================================================
// STATE - Centralized application state with event bus
// ============================================================

// Application state (single source of truth)
const state = {
    // Graph data
    graphData: null,
    seed: null,

    // Link index for fast lookups (built when graphData is set)
    // - byId: Map<linkId, link>
    // - byEndpoints: Map<"source|target", linkId[]> (supports parallel links)
    linkIndex: null,

    // Backend mode: 'offline' (localStorage) or 'online' (server)
    backendMode: 'offline',
    gameId: null, // UUID when in online mode
    isViewer: false, // true when viewing someone else's game (read-only)
    isOverlayMode: false, // true for OBS overlay (sync viewport, transparent bg)

    // Exploration mode
    explorationMode: true, // true = Explorer, false = Full Spoiler
    explorationState: {
        discovered: new Set(['Chapel of Anticipation']), // Start with starting area discovered
        discoveredLinks: new Set(), // Link UUIDs that have been traversed
        tags: new Map(),
    },
    frontierHighlightActive: false,

    // Graph visualization state
    nodePositions: new Map(),
    currentZoomTransform: null,
    selectedNodeId: null,
    simulation: null,

    // Sync state
    syncConnected: false,
    isStreamerHost: false,
    sessionCode: null,

    // Pending undiscover (to select placeholder after re-render)
    pendingUndiscoveredNodeId: null,
};

// Event bus for inter-module communication
const listeners = new Map();

/**
 * Subscribe to a state change event
 * @param {string} event - Event name
 * @param {Function} callback - Function to call when event fires
 * @returns {Function} Unsubscribe function
 */
export function subscribe(event, callback) {
    if (!listeners.has(event)) {
        listeners.set(event, new Set());
    }
    listeners.get(event).add(callback);

    // Return unsubscribe function
    return () => listeners.get(event).delete(callback);
}

/**
 * Emit an event to all subscribers
 * @param {string} event - Event name
 * @param {*} data - Data to pass to subscribers
 */
export function emit(event, data) {
    if (listeners.has(event)) {
        listeners.get(event).forEach(callback => {
            try {
                callback(data);
            } catch (err) {
                console.error(`Error in event handler for "${event}":`, err);
            }
        });
    }
}

// ============================================================
// STATE GETTERS (read-only access)
// ============================================================

export function getGraphData() {
    return state.graphData;
}

export function getSeed() {
    return state.seed;
}

export function isExplorationMode() {
    return state.explorationMode;
}

export function getExplorationState() {
    return state.explorationState;
}

export function isFrontierHighlightActive() {
    return state.frontierHighlightActive;
}

export function getNodePositions() {
    return state.nodePositions;
}

export function getCurrentZoomTransform() {
    return state.currentZoomTransform;
}

export function getSelectedNodeId() {
    return state.selectedNodeId;
}

export function getSimulation() {
    return state.simulation;
}

export function isSyncConnected() {
    return state.syncConnected;
}

export function isStreamerHost() {
    return state.isStreamerHost;
}

export function getSessionCode() {
    return state.sessionCode;
}

export function getBackendMode() {
    return state.backendMode;
}

export function getGameId() {
    return state.gameId;
}

export function isViewerMode() {
    return state.isViewer;
}

export function isOverlayMode() {
    return state.isOverlayMode;
}

// ============================================================
// STATE SETTERS (emit events on change)
// ============================================================

/**
 * Compute one-way property on links.
 *
 * Logic:
 * - Preexisting links: one-way if no reverse link exists in the data
 * - Random links: one-way only if marked as isInherentlyOneWay (teleports, warps, etc.)
 *   Otherwise assumed bidirectional (fog gates can be traversed both ways)
 */
function computeOneWayLinks(links) {
    if (!links || links.length === 0) return;

    // Build set of all link pairs for reverse lookup
    const linkPairs = new Set();
    links.forEach(l => {
        const { sourceId, targetId } = getLinkEndpoints(l);
        linkPairs.add(`${sourceId}|${targetId}`);
    });

    links.forEach(l => {
        const { sourceId, targetId } = getLinkEndpoints(l);
        const hasReverse = linkPairs.has(`${targetId}|${sourceId}`);

        if (l.type === 'random') {
            // Random links are bidirectional unless explicitly marked as one-way
            // (teleports, sending gates, abductions, etc.)
            l.oneWay = l.isInherentlyOneWay === true;
        } else {
            // Preexisting links: one-way if no reverse exists
            l.oneWay = !hasReverse;
        }
    });
}

/**
 * Build link index for fast lookups.
 * Called when graphData is set.
 */
function buildLinkIndex(links) {
    const byId = new Map();
    const byEndpoints = new Map();

    if (!links) return { byId, byEndpoints };

    for (const link of links) {
        // Index by ID
        if (link.id) {
            byId.set(link.id, link);
        }

        // Index by endpoints (supports parallel links)
        const { sourceId, targetId } = getLinkEndpoints(link);
        const key = `${sourceId}|${targetId}`;

        if (!byEndpoints.has(key)) {
            byEndpoints.set(key, []);
        }
        byEndpoints.get(key).push(link.id);

        // Also index reverse direction for bidirectional links
        if (!link.oneWay) {
            const reverseKey = `${targetId}|${sourceId}`;
            if (!byEndpoints.has(reverseKey)) {
                byEndpoints.set(reverseKey, []);
            }
            // Only add if not already there (avoid duplicates)
            if (!byEndpoints.get(reverseKey).includes(link.id)) {
                byEndpoints.get(reverseKey).push(link.id);
            }
        }
    }

    return { byId, byEndpoints };
}

export function setGraphData(data) {
    // Compute one-way links before storing (ensures consistency across all entry points)
    if (data && data.links) {
        computeOneWayLinks(data.links);
    }
    state.graphData = data;
    // Build link index for fast lookups
    state.linkIndex = buildLinkIndex(data?.links);
    emit('graphDataChanged', data);
}

export function getLinkIndex() {
    return state.linkIndex;
}

export function setSeed(seed) {
    const oldSeed = state.seed;
    state.seed = seed;
    if (oldSeed !== seed) {
        emit('seedChanged', { oldSeed, newSeed: seed });
    }
}

export function setExplorationMode(mode) {
    const oldMode = state.explorationMode;
    state.explorationMode = mode;
    if (oldMode !== mode) {
        emit('explorationModeChanged', mode);
    }
}

export function setExplorationState(explorationState) {
    state.explorationState = explorationState;
    emit('explorationStateChanged', explorationState);
}

export function setFrontierHighlightActive(active) {
    state.frontierHighlightActive = active;
    emit('frontierHighlightChanged', active);
}

export function setCurrentZoomTransform(transform) {
    state.currentZoomTransform = transform;
    // No event - this changes too frequently
}

export function setSelectedNodeId(nodeId) {
    state.selectedNodeId = nodeId;
    emit('selectionChanged', nodeId);
}

export function setSimulation(sim) {
    state.simulation = sim;
}

export function setSyncState(connected, isHost, code) {
    state.syncConnected = connected;
    state.isStreamerHost = isHost;
    state.sessionCode = code;
    emit('syncStateChanged', { connected, isHost, code });
}

export function setBackendMode(mode) {
    state.backendMode = mode;
    emit('backendModeChanged', mode);
}

export function setGameId(gameId) {
    state.gameId = gameId;
}

export function setIsViewer(isViewer) {
    state.isViewer = isViewer;
}

export function setIsOverlayMode(isOverlay) {
    state.isOverlayMode = isOverlay;
}

export function setNodePositions(positions) {
    state.nodePositions = positions;
}

export function setPendingUndiscoveredNodeId(nodeId) {
    state.pendingUndiscoveredNodeId = nodeId;
}

export function getPendingUndiscoveredNodeId() {
    return state.pendingUndiscoveredNodeId;
}

export function clearPendingUndiscoveredNodeId() {
    state.pendingUndiscoveredNodeId = null;
}

// ============================================================
// EXPLORATION STATE HELPERS
// ============================================================

export function isDiscovered(nodeId) {
    return state.explorationState.discovered.has(nodeId);
}

export function discoverNode(nodeId) {
    if (!state.explorationState.discovered.has(nodeId)) {
        state.explorationState.discovered.add(nodeId);
        emit('nodeDiscovered', nodeId);
        return true;
    }
    return false;
}

export function undiscoverNode(nodeId) {
    if (state.explorationState.discovered.has(nodeId)) {
        state.explorationState.discovered.delete(nodeId);
        state.explorationState.tags.delete(nodeId);
        emit('nodeUndiscovered', nodeId);
        return true;
    }
    return false;
}

// ============================================================
// DISCOVERED LINKS HELPERS
// ============================================================

/**
 * Extract source and target IDs from a link object.
 * Handles both D3 simulation format (objects with .id) and raw format (strings).
 * @param {Object} link - Link object with source/target properties
 * @returns {{sourceId: string, targetId: string}}
 */
export function getLinkEndpoints(link) {
    return {
        sourceId: typeof link.source === 'object' ? link.source.id : link.source,
        targetId: typeof link.target === 'object' ? link.target.id : link.target,
    };
}

/**
 * Create an endpoint key from source and target (for index lookups)
 * Format: "sourceId|targetId"
 */
export function makeEndpointKey(sourceId, targetId) {
    return `${sourceId}|${targetId}`;
}

/**
 * Get link object by its UUID
 */
export function getLinkById(linkId) {
    return state.linkIndex?.byId.get(linkId);
}

/**
 * Get all link IDs connecting two nodes (supports parallel links)
 * Returns array of link UUIDs
 */
export function getLinkIdsByEndpoints(sourceId, targetId) {
    if (!state.linkIndex) return [];
    const key = makeEndpointKey(sourceId, targetId);
    return state.linkIndex.byEndpoints.get(key) || [];
}

/**
 * Check if a specific link (by UUID) has been discovered
 */
export function isLinkIdDiscovered(linkId) {
    return state.explorationState.discoveredLinks.has(linkId);
}

/**
 * Check if any link between two nodes has been discovered
 * (For cases where we don't care which specific parallel link)
 */
export function isLinkDiscovered(sourceId, targetId) {
    const linkIds = getLinkIdsByEndpoints(sourceId, targetId);
    return linkIds.some(id => state.explorationState.discoveredLinks.has(id));
}

/**
 * Mark a link as discovered by its UUID
 * @param {string} linkId - Link UUID
 */
export function discoverLinkById(linkId) {
    // Guard against null/undefined linkIds
    if (!linkId) {
        return false;
    }
    const added = !state.explorationState.discoveredLinks.has(linkId);
    if (added) {
        state.explorationState.discoveredLinks.add(linkId);
        const link = getLinkById(linkId);
        if (link) {
            emit('linkDiscovered', { linkId, sourceId: link.source, targetId: link.target });
        }
    }
    return added;
}

/**
 * Mark a link as discovered by source/target
 * If multiple parallel links exist, discovers only the first one found
 * @param {string} sourceId - Source node ID
 * @param {string} targetId - Target node ID
 * @returns {string|null} The link UUID that was discovered, or null if no link found
 */
export function discoverLink(sourceId, targetId) {
    const linkIds = getLinkIdsByEndpoints(sourceId, targetId);
    if (linkIds.length === 0) return null;

    // Find first undiscovered link, or use first link if all discovered
    const linkId = linkIds.find(id => !state.explorationState.discoveredLinks.has(id)) || linkIds[0];
    discoverLinkById(linkId);
    return linkId;
}

/**
 * Discover all links between two nodes (for preexisting link propagation)
 * @param {string} sourceId - Source node ID
 * @param {string} targetId - Target node ID
 * @returns {string[]} Array of link UUIDs that were discovered
 */
export function discoverAllLinksBetween(sourceId, targetId) {
    const linkIds = getLinkIdsByEndpoints(sourceId, targetId);
    const discovered = [];
    for (const linkId of linkIds) {
        if (discoverLinkById(linkId)) {
            discovered.push(linkId);
        }
    }
    return discovered;
}

/**
 * Remove a link from discovered set by UUID
 */
export function undiscoverLinkById(linkId) {
    return state.explorationState.discoveredLinks.delete(linkId);
}

/**
 * Remove all discovered links involving a specific node
 */
export function undiscoverLinksForNode(nodeId) {
    if (!state.linkIndex) return 0;

    const toRemove = [];
    state.explorationState.discoveredLinks.forEach(linkId => {
        const link = state.linkIndex.byId.get(linkId);
        if (link) {
            const { sourceId, targetId } = getLinkEndpoints(link);
            if (sourceId === nodeId || targetId === nodeId) {
                toRemove.push(linkId);
            }
        }
    });
    toRemove.forEach(linkId => state.explorationState.discoveredLinks.delete(linkId));
    return toRemove.length;
}

export function getNodeTags(nodeId) {
    return state.explorationState.tags.get(nodeId) || [];
}

export function setNodeTags(nodeId, tags) {
    if (tags && tags.length > 0) {
        state.explorationState.tags.set(nodeId, tags);
    } else {
        state.explorationState.tags.delete(nodeId);
    }
    emit('nodeTagsChanged', { nodeId, tags });
}

export function toggleNodeTag(nodeId, tagId) {
    const currentTags = getNodeTags(nodeId);
    const tagIndex = currentTags.indexOf(tagId);

    if (tagIndex >= 0) {
        currentTags.splice(tagIndex, 1);
    } else {
        currentTags.push(tagId);
    }

    setNodeTags(nodeId, currentTags);
    return currentTags;
}

// ============================================================
// NODE POSITIONS HELPERS
// ============================================================

export function saveNodePosition(nodeId, x, y) {
    if (typeof x === 'number' && typeof y === 'number' && !isNaN(x) && !isNaN(y) && isFinite(x) && isFinite(y)) {
        state.nodePositions.set(nodeId, { x, y });
    }
}

export function getNodePosition(nodeId) {
    return state.nodePositions.get(nodeId);
}

export function saveAllNodePositions() {
    if (!state.simulation) return;

    state.simulation.nodes().forEach(node => {
        if (node.x !== undefined && node.y !== undefined) {
            saveNodePosition(node.id, node.x, node.y);
        }
    });

    emit('nodePositionsSaved');
}

// ============================================================
// PERSISTENCE (localStorage)
// ============================================================

const STORAGE_KEY_PREFIX = 'er-fog-exploration-';

function getStorageKey(seed) {
    return STORAGE_KEY_PREFIX + seed;
}

export function saveExplorationToStorage() {
    if (!state.seed || !state.explorationState) return;

    const toSave = {
        discovered: Array.from(state.explorationState.discovered),
        discoveredLinks: Array.from(state.explorationState.discoveredLinks),
        tags: Object.fromEntries(state.explorationState.tags),
    };

    try {
        localStorage.setItem(getStorageKey(state.seed), JSON.stringify(toSave));
    } catch (err) {
        console.error('Failed to save exploration state:', err);
    }
}

export function loadExplorationFromStorage(seed) {
    const saved = localStorage.getItem(getStorageKey(seed));
    if (!saved) return null;

    try {
        const parsed = JSON.parse(saved);
        return {
            discovered: new Set(parsed.discovered || []),
            discoveredLinks: new Set(parsed.discoveredLinks || []),
            tags: new Map(Object.entries(parsed.tags || {})),
        };
    } catch (err) {
        console.error('Failed to load exploration state:', err);
        return null;
    }
}

export function clearExplorationStorage(seed) {
    localStorage.removeItem(getStorageKey(seed || state.seed));
}

// ============================================================
// GRAPH DATA PERSISTENCE (offline mode)
// ============================================================

const GRAPH_STORAGE_KEY_PREFIX = 'er-fog-graph-';

function getGraphStorageKey(seed) {
    return GRAPH_STORAGE_KEY_PREFIX + seed;
}

/**
 * Save graph data to localStorage (for offline mode persistence).
 * This allows the graph to survive page reloads without re-uploading.
 */
export function saveGraphToStorage() {
    if (!state.seed || !state.graphData) return;

    try {
        localStorage.setItem(getGraphStorageKey(state.seed), JSON.stringify(state.graphData));
    } catch (err) {
        console.error('Failed to save graph data:', err);
    }
}

/**
 * Load graph data from localStorage.
 * @param {string} seed - The game seed to load
 * @returns {Object|null} The graph data if found, null otherwise
 */
export function loadGraphFromStorage(seed) {
    const saved = localStorage.getItem(getGraphStorageKey(seed));
    if (!saved) return null;

    try {
        return JSON.parse(saved);
    } catch (err) {
        console.error('Failed to load graph data:', err);
        return null;
    }
}

/**
 * Clear graph data from localStorage.
 */
export function clearGraphStorage(seed) {
    localStorage.removeItem(getGraphStorageKey(seed || state.seed));
}

/**
 * Get all saved offline game seeds from localStorage.
 * @returns {string[]} Array of seed strings
 */
export function getOfflineGameSeeds() {
    const seeds = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(GRAPH_STORAGE_KEY_PREFIX)) {
            seeds.push(key.substring(GRAPH_STORAGE_KEY_PREFIX.length));
        }
    }
    return seeds;
}

// ============================================================
// CONSTANTS
// ============================================================

export const START_NODE = 'Chapel of Anticipation';

export const AVAILABLE_TAGS = [
    { id: 'warning', emoji: '⚠️' },
    { id: 'later', emoji: '⏳' },
    { id: 'loot', emoji: '💰' },
    { id: 'done', emoji: '✅' },
    { id: 'star', emoji: '⭐' },
    { id: 'blocked', emoji: '❌' },
    { id: 'key', emoji: '🔑' },
];
