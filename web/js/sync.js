// ============================================================
// SYNC - WebSocket-based streamer sync
// ============================================================

import * as State from './state.js';
import * as Toast from './toast.js';
import * as Auth from './auth.js';

// =============================================================================
// Configuration
// =============================================================================

// WebSocket server URL - same host as page
function getWsUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}`;
}

const MAX_RECONNECT_DURATION = 5 * 60 * 1000;  // 5 minutes total
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;  // Cap at 30 seconds between attempts

let syncThrottle = null;
let lastSyncedViewport = null;
let isRenderingGraph = false;
let isSyncing = false;

// Game WebSocket variables
let gameWs = null;
let currentGameId = null;
let gameWsReconnectAttempts = 0;
let gameWsReconnectStartTime = null;
let gameWsIsReconnecting = false;
let gameWsIsHost = false;  // Track if we connected as host or viewer

// Client-side heartbeat monitoring (detect if server stops sending pings)
const HEARTBEAT_EXPECTED_INTERVAL = 15000;  // Server sends ping every 15s
const HEARTBEAT_GRACE_PERIOD = 15000;       // Allow 15s extra before considering dead
let lastGameWsPing = null;
let gameWsHeartbeatCheckInterval = null;

// URL parameters for viewer options
const urlParams = new URLSearchParams(window.location.search);
// Counter position: off, tl, tr, bl, br (default), t, b, l, r (centered on edge)
const counterPosition = urlParams.get('counter') || 'br';
// Counter size: sm (small), md (medium, default), lg (large), xl (extra-large)
const counterSize = urlParams.get('size') || 'md';

// =============================================================================
// Heartbeat Monitoring
// =============================================================================

function startGameWsHeartbeatMonitoring() {
    lastGameWsPing = Date.now();
    stopGameWsHeartbeatMonitoring();  // Clear any existing interval

    gameWsHeartbeatCheckInterval = setInterval(() => {
        if (!gameWs || gameWs.readyState !== WebSocket.OPEN) {
            stopGameWsHeartbeatMonitoring();
            return;
        }

        const timeSinceLastPing = Date.now() - lastGameWsPing;
        const timeout = HEARTBEAT_EXPECTED_INTERVAL + HEARTBEAT_GRACE_PERIOD;

        if (timeSinceLastPing > timeout) {
            console.log(`No server ping for game WS in ${Math.round(timeSinceLastPing / 1000)}s, connection likely dead`);
            // Force close to trigger reconnection
            gameWs.close();
            stopGameWsHeartbeatMonitoring();
        }
    }, 5000);  // Check every 5 seconds
}

function stopGameWsHeartbeatMonitoring() {
    if (gameWsHeartbeatCheckInterval) {
        clearInterval(gameWsHeartbeatCheckInterval);
        gameWsHeartbeatCheckInterval = null;
    }
}

function onGameWsPingReceived() {
    lastGameWsPing = Date.now();
}

// =============================================================================
// Sync Logic
// =============================================================================

function syncState() {
    if (!State.isStreamerHost() || isSyncing) return;

    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

    // Throttle syncs to avoid flooding
    if (syncThrottle) return;

    syncThrottle = setTimeout(() => {
        syncThrottle = null;

        // Re-check connection state (may have changed during throttle delay)
        if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

        isSyncing = true;
        try {
            const state = getFullSyncState();

            gameWs.send(JSON.stringify({
                type: 'visual_state',
                state
            }));
        } finally {
            isSyncing = false;
        }
    }, 50);
}

function syncViewport() {
    if (!State.isStreamerHost() || isRenderingGraph) return;

    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

    // Viewport sync is handled by the general sync
    syncState();
}

// =============================================================================
// State Serialization
// =============================================================================

function getFullSyncState() {
    const simulation = State.getSimulation();
    if (simulation) {
        simulation.nodes().forEach(node => {
            if (node.x !== undefined && node.y !== undefined) {
                State.saveNodePosition(node.id, node.x, node.y);
            }
        });
    }

    const nodeElements = d3.selectAll(".node");
    const linkElements = d3.selectAll(".link");

    const graphData = State.getGraphData();
    const nodePositions = State.getNodePositions();
    const explorationState = State.getExplorationState();

    // Build nodes state from DOM (includes placeholders)
    const nodesState = {};
    nodeElements.each(function(d) {
        const nodeEl = d3.select(this);
        const pos = nodePositions.get(d.id);

        // For placeholders, get position from simulation data
        const x = d.x !== undefined ? d.x : (pos ? pos.x : 0);
        const y = d.y !== undefined ? d.y : (pos ? pos.y : 0);

        const tags = explorationState?.tags?.get(d.id) || [];
        const discovered = d.isPlaceholder ? false : (explorationState?.discovered?.has(d.id) || false);

        nodesState[d.id] = {
            x: x,
            y: y,
            visible: nodeEl.style("display") !== "none",
            highlighted: nodeEl.classed("highlighted"),
            dimmed: nodeEl.classed("dimmed"),
            frontierHighlight: nodeEl.classed("frontier-highlight"),
            accessHighlight: nodeEl.classed("access-highlight"),
            tagHighlighted: nodeEl.classed("tag-highlighted"),
            discovered: discovered,
            tags: tags,
            isBoss: d.isBoss || false,
            scaling: d.scaling || null,
            isPlaceholder: d.isPlaceholder || false,
            realId: d.realId || null,
            sourceNodeId: d.sourceNodeId || null
        };
    });

    // Build links state from DOM (includes links to placeholders)
    const linksState = {};
    linkElements.each(function(d) {
        const linkEl = d3.select(this);
        const sourceId = typeof d.source === 'object' ? d.source.id : d.source;
        const targetId = typeof d.target === 'object' ? d.target.id : d.target;

        linksState[`${sourceId}->${targetId}`] = {
            visible: linkEl.style("display") !== "none",
            highlighted: linkEl.classed("highlighted"),
            dimmed: linkEl.classed("dimmed"),
            frontierHighlight: linkEl.classed("frontier-highlight"),
            type: d.type || null,
            oneWay: d.oneWay || false,
            // Store original target for placeholder links
            originalTarget: d.originalTarget || null,
            originalSource: d.originalSource || null
        };
    });

    // Also include original graph nodes (undiscovered ones) for viewer to rebuild
    if (graphData && graphData.nodes) {
        graphData.nodes.forEach(n => {
            if (!nodesState[n.id]) {
                nodesState[n.id] = {
                    x: 0,
                    y: 0,
                    visible: false,
                    highlighted: false,
                    dimmed: false,
                    frontierHighlight: false,
                    accessHighlight: false,
                    tagHighlighted: false,
                    discovered: false,
                    tags: [],
                    isBoss: n.isBoss || false,
                    scaling: n.scaling || null,
                    isPlaceholder: false,
                    isOriginalNode: true
                };
            }
        });
    }

    // Also include original graph links for viewer to rebuild the graph
    if (graphData && graphData.links) {
        graphData.links.forEach(l => {
            const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
            const targetId = typeof l.target === 'object' ? l.target.id : l.target;
            const key = `${sourceId}->${targetId}`;
            // Only add if not already present (don't overwrite visual state)
            if (!linksState[key]) {
                linksState[key] = {
                    visible: false,
                    highlighted: false,
                    dimmed: false,
                    frontierHighlight: false,
                    type: l.type || null,
                    oneWay: l.oneWay || false,
                    isOriginalLink: true
                };
            }
        });
    }

    const transform = State.getCurrentZoomTransform();

    // Include discovered links for proper link visibility on viewer
    const discoveredLinks = explorationState?.discoveredLinks
        ? Array.from(explorationState.discoveredLinks)
        : [];

    // Use server-calculated stats if available, otherwise calculate locally
    let discoveredCount, totalAreas;
    if (graphData?.metadata?.discoveryCount !== undefined && graphData?.metadata?.totalZones !== undefined) {
        discoveredCount = graphData.metadata.discoveryCount;
        totalAreas = graphData.metadata.totalZones;
    } else {
        totalAreas = graphData?.nodes?.length || 0;
        discoveredCount = 0;
        if (explorationState?.discoveredLinks && graphData?.nodes) {
            const nodeIds = new Set(graphData.nodes.map(n => n.id));
            const discoveredFromLinks = new Set();
            for (const linkKey of explorationState.discoveredLinks) {
                const [source, target] = linkKey.split('|');
                if (nodeIds.has(source)) discoveredFromLinks.add(source);
                if (nodeIds.has(target)) discoveredFromLinks.add(target);
            }
            discoveredCount = discoveredFromLinks.size;
        }
    }

    return {
        created: Date.now(),
        explorationMode: State.isExplorationMode(),
        viewport: {
            x: transform?.x || 0,
            y: transform?.y || 0,
            k: transform?.k || 1,
            hostWidth: window.innerWidth,
            hostHeight: window.innerHeight
        },
        selectedNodeId: State.getSelectedNodeId() || null,
        frontierHighlightActive: State.isFrontierHighlightActive(),
        nodes: nodesState,
        links: linksState,
        discoveredLinks: discoveredLinks,
        discoveredCount: discoveredCount,
        totalAreas: totalAreas
    };
}

// =============================================================================
// State Application (viewer side)
// =============================================================================

function applySessionData(data) {
    if (!data) return;

    const hasNodes = data.nodes && Object.keys(data.nodes).length > 0;

    const currentGraphData = State.getGraphData();
    if (hasNodes && !currentGraphData) {
        buildGraphFromSessionData(data);
        return;
    }

    const rerendering = applyVisualState(data);

    if (data.viewport && !State.isStreamerHost() && !rerendering) {
        applyViewport(data.viewport);
    }
}

function buildGraphFromSessionData(data) {
    console.log("Building graph from session data...");

    // Set exploration mode FIRST so renderGraph creates placeholders correctly
    if (data.explorationMode !== undefined) {
        State.setExplorationMode(data.explorationMode);
    }

    const nodes = [];
    const explorationState = { discovered: new Set(), discoveredLinks: new Set(), tags: new Map() };

    for (const [id, nodeState] of Object.entries(data.nodes)) {
        // Skip placeholder nodes - they will be recreated by renderGraph
        if (nodeState.isPlaceholder) {
            continue;
        }

        nodes.push({
            id: id,
            isBoss: nodeState.isBoss || false,
            scaling: nodeState.scaling || null,
            x: nodeState.x,
            y: nodeState.y
        });

        if (nodeState.x !== undefined && nodeState.y !== undefined) {
            State.saveNodePosition(id, nodeState.x, nodeState.y);
        }

        if (nodeState.discovered) explorationState.discovered.add(id);
        if (nodeState.tags && nodeState.tags.length > 0) {
            explorationState.tags.set(id, nodeState.tags);
        }
    }

    const links = [];
    const seenLinks = new Set();
    if (data.links) {
        for (const [linkKey, linkState] of Object.entries(data.links)) {
            const [source, target] = linkKey.split('->');

            // Skip links involving placeholders - they will be recreated by renderGraph
            if (source.startsWith('???_') || target.startsWith('???_')) {
                continue;
            }

            // Avoid duplicates
            if (seenLinks.has(linkKey)) continue;
            seenLinks.add(linkKey);

            links.push({
                source: source,
                target: target,
                type: linkState.type || 'fog',
                oneWay: linkState.oneWay || false
            });
        }
    }

    // Restore discovered links from sync data
    if (data.discoveredLinks && Array.isArray(data.discoveredLinks)) {
        data.discoveredLinks.forEach(linkId => {
            explorationState.discoveredLinks.add(linkId);
        });
    }

    const graphData = { nodes, links, metadata: {} };
    State.setGraphData(graphData);
    State.setExplorationState(explorationState);

    // Set frontier highlight state so it persists
    if (data.frontierHighlightActive !== undefined) {
        State.setFrontierHighlightActive(data.frontierHighlightActive);
    }

    const uploadScreen = document.getElementById('upload-screen');
    if (uploadScreen) {
        uploadScreen.classList.add('hidden');
    }
    const mainUI = document.getElementById('main-ui');
    if (mainUI) {
        mainUI.classList.add('visible');
    }

    State.emit('graphNeedsRender', { preservePositions: true });

    setTimeout(() => {
        applyVisualState(data);
        if (data.viewport) applyViewport(data.viewport);
    }, 500);
}

function applyViewport(vp) {
    if (!vp || vp.x === undefined || isRenderingGraph) return;

    // Only sync viewport in overlay mode (OBS)
    // Interactive viewers control their own viewport
    if (!State.isOverlayMode()) return;

    const svg = d3.select("#graph-container svg");
    const g = svg.select("g");

    if (!svg.node() || !g.node()) {
        setTimeout(() => applyViewport(vp), 200);
        return;
    }

    if (lastSyncedViewport &&
        Math.abs(vp.x - lastSyncedViewport.x) <= 1 &&
        Math.abs(vp.y - lastSyncedViewport.y) <= 1 &&
        Math.abs(vp.k - lastSyncedViewport.k) <= 0.01) {
        return;
    }

    lastSyncedViewport = { x: vp.x, y: vp.y, k: vp.k };

    if (!vp || typeof vp.x !== 'number' || typeof vp.y !== 'number' || typeof vp.k !== 'number' ||
        isNaN(vp.x) || isNaN(vp.y) || isNaN(vp.k) || !isFinite(vp.x) || !isFinite(vp.y) || !isFinite(vp.k) || vp.k <= 0) {
        console.warn("Invalid viewport data:", vp);
        return;
    }

    const viewerWidth = window.innerWidth;
    const viewerHeight = window.innerHeight;
    const hostWidth = vp.hostWidth || viewerWidth;
    const hostHeight = vp.hostHeight || viewerHeight;

    const hostCenterX = (hostWidth / 2 - vp.x) / vp.k;
    const hostCenterY = (hostHeight / 2 - vp.y) / vp.k;
    const x = viewerWidth / 2 - hostCenterX * vp.k;
    const y = viewerHeight / 2 - hostCenterY * vp.k;

    if (isNaN(x) || isNaN(y) || !isFinite(x) || !isFinite(y) || !isFinite(vp.k) || vp.k <= 0) {
        console.warn("Invalid calculated viewport transform:", { x, y, vp });
        return;
    }

    const transform = d3.zoomIdentity.translate(x, y).scale(vp.k);
    State.setCurrentZoomTransform(transform);

    g.transition()
        .duration(300)
        .attr("transform", `translate(${x},${y}) scale(${vp.k})`);
}

/**
 * Apply only positions and discovery state from visual_state (for interactive viewers).
 * Ignores selection, highlights, and viewport.
 */
function applyPositionsAndDiscoveryOnly(data) {
    if (!data.nodes) return;

    const simulation = State.getSimulation();
    const d3Nodes = simulation ? simulation.nodes() : [];
    let positionsChanged = false;
    let explorationChanged = false;

    const explorationState = State.getExplorationState();

    // Save and apply node positions
    for (const [id, nodeState] of Object.entries(data.nodes)) {
        if (nodeState.x !== undefined && nodeState.y !== undefined &&
            !isNaN(nodeState.x) && !isNaN(nodeState.y) && isFinite(nodeState.x) && isFinite(nodeState.y)) {
            State.saveNodePosition(id, nodeState.x, nodeState.y);

            const simNode = d3Nodes.find(n => n.id === id);
            if (simNode && (Math.abs(simNode.x - nodeState.x) > 1 || Math.abs(simNode.y - nodeState.y) > 1)) {
                simNode.x = nodeState.x;
                simNode.y = nodeState.y;
                simNode.fx = nodeState.x;
                simNode.fy = nodeState.y;
                positionsChanged = true;
            }
        }

        // Update discovery state
        if (explorationState && !nodeState.isPlaceholder) {
            const wasDiscovered = explorationState.discovered.has(id);
            const isDiscovered = nodeState.discovered || false;
            if (wasDiscovered !== isDiscovered) {
                explorationChanged = true;
                if (isDiscovered) {
                    explorationState.discovered.add(id);
                } else {
                    explorationState.discovered.delete(id);
                }
            }

            // Update tags
            const oldTags = explorationState.tags.get(id) || [];
            const newTags = nodeState.tags || [];
            if (JSON.stringify(oldTags) !== JSON.stringify(newTags)) {
                explorationChanged = true;
                if (newTags.length > 0) {
                    explorationState.tags.set(id, newTags);
                } else {
                    explorationState.tags.delete(id);
                }
            }
        }
    }

    // Sync discovered links
    if (data.discoveredLinks && Array.isArray(data.discoveredLinks) && explorationState) {
        const newDiscoveredLinks = new Set(data.discoveredLinks);
        const currentLinks = explorationState.discoveredLinks || new Set();

        if (newDiscoveredLinks.size !== currentLinks.size ||
            [...newDiscoveredLinks].some(l => !currentLinks.has(l))) {
            explorationChanged = true;
            explorationState.discoveredLinks = newDiscoveredLinks;
        }
    }

    // Apply position changes to DOM
    if (positionsChanged) {
        updatePositionsInDOM(d3Nodes);
    }

    // Re-render if discovery changed
    if (explorationChanged) {
        State.saveAllNodePositions();
        State.emit('graphNeedsRender', { preservePositions: true });
    }
}

function applyVisualState(data) {
    if (!data.nodes) return false;

    if (data.explorationMode !== undefined) {
        const currentMode = State.isExplorationMode();
        if (data.explorationMode !== currentMode) {
            State.setExplorationMode(data.explorationMode);
            isRenderingGraph = true;
            State.saveAllNodePositions();
            State.emit('graphNeedsRender', { preservePositions: true });
            setTimeout(() => {
                isRenderingGraph = false;
                applyVisualClasses(data);
                if (data.viewport) applyViewport(data.viewport);
            }, 200);
            return true;
        }
    }

    const simulation = State.getSimulation();
    const d3Nodes = simulation ? simulation.nodes() : [];
    let positionsChanged = false;
    let explorationChanged = false;

    const explorationState = State.getExplorationState();

    // First pass: save ALL node positions
    for (const [id, nodeState] of Object.entries(data.nodes)) {
        if (nodeState.x !== undefined && nodeState.y !== undefined &&
            !isNaN(nodeState.x) && !isNaN(nodeState.y) && isFinite(nodeState.x) && isFinite(nodeState.y)) {
            State.saveNodePosition(id, nodeState.x, nodeState.y);
        }
    }

    // Second pass: apply states to existing simulation nodes and detect missing nodes
    let hasMissingNodes = false;
    for (const [id, nodeState] of Object.entries(data.nodes)) {
        const simNode = d3Nodes.find(n => n.id === id);

        // Check if this node exists in the viewer's DOM
        if (!simNode && (nodeState.highlighted || nodeState.frontierHighlight || id === data.selectedNodeId)) {
            // A highlighted node doesn't exist in viewer - need to re-render
            hasMissingNodes = true;
        }

        if (simNode && nodeState.x !== undefined && nodeState.y !== undefined &&
            !isNaN(nodeState.x) && !isNaN(nodeState.y) && isFinite(nodeState.x) && isFinite(nodeState.y)) {
            if (Math.abs(simNode.x - nodeState.x) > 1 || Math.abs(simNode.y - nodeState.y) > 1) {
                simNode.x = nodeState.x;
                simNode.y = nodeState.y;
                simNode.fx = nodeState.x;
                simNode.fy = nodeState.y;
                positionsChanged = true;
            }
        }

        if (explorationState && !nodeState.isPlaceholder) {
            const wasDiscovered = explorationState.discovered.has(id);
            const isDiscovered = nodeState.discovered || false;
            if (wasDiscovered !== isDiscovered) {
                explorationChanged = true;
                if (isDiscovered) {
                    explorationState.discovered.add(id);
                } else {
                    explorationState.discovered.delete(id);
                }
            }

            const oldTags = explorationState.tags.get(id) || [];
            const newTags = nodeState.tags || [];
            if (JSON.stringify(oldTags) !== JSON.stringify(newTags)) {
                explorationChanged = true;
                if (newTags.length > 0) {
                    explorationState.tags.set(id, newTags);
                } else {
                    explorationState.tags.delete(id);
                }
            }
        }
    }

    // Sync discovered links
    if (data.discoveredLinks && Array.isArray(data.discoveredLinks) && explorationState) {
        const newDiscoveredLinks = new Set(data.discoveredLinks);
        const currentLinks = explorationState.discoveredLinks || new Set();

        // Check if links changed
        if (newDiscoveredLinks.size !== currentLinks.size ||
            [...newDiscoveredLinks].some(l => !currentLinks.has(l))) {
            explorationChanged = true;
            explorationState.discoveredLinks = newDiscoveredLinks;
        }
    }

    // If we have missing highlighted nodes, force a re-render
    if (hasMissingNodes && !explorationChanged) {
        explorationChanged = true;
    }

    if (explorationChanged) {
        isRenderingGraph = true;
        State.saveAllNodePositions();

        State.emit('graphNeedsRender', { preservePositions: true });
        setTimeout(() => {
            isRenderingGraph = false;
            applyVisualClasses(data);
        }, 500);
        return true;
    }

    if (data.frontierHighlightActive !== undefined) {
        const currentFrontierActive = State.isFrontierHighlightActive();
        if (data.frontierHighlightActive !== currentFrontierActive) {
            updateFrontierCheckboxState(data.frontierHighlightActive);
        }
    }

    applyVisualClasses(data);

    if (positionsChanged) {
        updatePositionsInDOM(d3Nodes);
    }

    if (data.selectedNodeId !== undefined) {
        State.setSelectedNodeId(data.selectedNodeId || null);
    }

    return false;
}

function updateFrontierCheckboxState(active) {
    const frontierCheckbox = document.getElementById('show-frontier-checkbox');
    if (frontierCheckbox) {
        frontierCheckbox.checked = active;
    }
}

function applyVisualClasses(data) {
    const selectedId = data.selectedNodeId || null;

    d3.selectAll(".node").each(function(d) {
        const nodeState = data.nodes?.[d.id];
        const node = d3.select(this);

        if (nodeState) {
            node.classed("highlighted", nodeState.highlighted || false)
                .classed("dimmed", nodeState.dimmed || false)
                .classed("frontier-highlight", nodeState.frontierHighlight || false)
                .classed("access-highlight", nodeState.accessHighlight || false)
                .classed("tag-highlighted", nodeState.tagHighlighted || false);
        }

        // Handle selection separately - apply even if nodeState doesn't exist
        node.classed("viewer-selected", d.id === selectedId);

        // Show selection ring in viewer modes (overlay or interactive)
        if (d.id === selectedId && State.isViewerMode()) {
            if (node.select(".selection-ring").empty()) {
                const circle = node.select("circle");
                const r = parseFloat(circle.attr("r")) || 7;
                node.insert("circle", "circle")
                    .attr("class", "selection-ring")
                    .attr("r", r + 8);
            }
        } else {
            node.select(".selection-ring").remove();
        }
    });

    if (data.links) {
        d3.selectAll(".link").each(function(d) {
            const sourceId = typeof d.source === 'object' ? d.source.id : d.source;
            const targetId = typeof d.target === 'object' ? d.target.id : d.target;
            const linkKey = `${sourceId}->${targetId}`;
            const linkState = data.links[linkKey];
            if (linkState) {
                d3.select(this)
                    .classed("highlighted", linkState.highlighted || false)
                    .classed("dimmed", linkState.dimmed || false)
                    .classed("frontier-highlight", linkState.frontierHighlight || false);
            }
        });
    }

    // Update viewer discovery counter
    updateViewerDiscoveryCounter(data);
}

// Update viewer discovery counter (OBS overlay only)
function updateViewerDiscoveryCounter(data) {
    // Counter only shows in overlay mode (OBS browser source)
    if (!State.isOverlayMode()) return;

    const counter = document.getElementById('viewer-discovery-counter');
    if (!counter) return;

    // Handle counter disabled via URL param
    if (counterPosition === 'off') {
        counter.classList.add('hidden');
        return;
    }

    const explorationMode = data.explorationMode;
    const discoveredCount = data.discoveredCount || 0;
    const totalAreas = data.totalAreas || 0;

    if (!explorationMode || totalAreas === 0) {
        counter.classList.add('hidden');
        return;
    }

    // Apply position class based on URL param
    counter.classList.remove('pos-tl', 'pos-tr', 'pos-bl', 'pos-br');
    counter.classList.add(`pos-${counterPosition}`);

    // Apply size class based on URL param
    counter.classList.remove('size-sm', 'size-md', 'size-lg', 'size-xl');
    counter.classList.add(`size-${counterSize}`);

    const discoveredEl = document.getElementById('viewer-discovered');
    const totalEl = document.getElementById('viewer-total');
    const percentEl = document.getElementById('viewer-percent');
    const progressBar = document.getElementById('viewer-progress-bar');

    if (discoveredEl && totalEl) {
        const oldCount = parseInt(discoveredEl.textContent) || 0;
        const percent = Math.round((discoveredCount / totalAreas) * 100);

        discoveredEl.textContent = discoveredCount;
        totalEl.textContent = totalAreas;

        // Update percentage display
        if (percentEl) {
            percentEl.textContent = `(${percent}%)`;
        }

        // Update progress bar
        if (progressBar) {
            progressBar.style.width = `${percent}%`;
        }

        counter.classList.remove('hidden');

        // Trigger pulse animation on change
        if (oldCount !== discoveredCount) {
            counter.classList.remove('updated');
            // Force reflow to restart animation
            void counter.offsetWidth;
            counter.classList.add('updated');
        }
    }
}

function updatePositionsInDOM(d3Nodes) {
    d3.selectAll(".node")
        .transition()
        .duration(300)
        .attr("transform", d => {
            const x = (typeof d.x === 'number' && !isNaN(d.x) && isFinite(d.x)) ? d.x : 0;
            const y = (typeof d.y === 'number' && !isNaN(d.y) && isFinite(d.y)) ? d.y : 0;
            return `translate(${x},${y})`;
        });

    d3.selectAll(".link")
        .transition()
        .duration(300)
        .attr("d", d => {
            const sourceX = (typeof d.source.x === 'number' && !isNaN(d.source.x)) ? d.source.x : 0;
            const sourceY = (typeof d.source.y === 'number' && !isNaN(d.source.y)) ? d.source.y : 0;
            const targetX = (typeof d.target.x === 'number' && !isNaN(d.target.x)) ? d.target.x : 0;
            const targetY = (typeof d.target.y === 'number' && !isNaN(d.target.y)) ? d.target.y : 0;
            const dx = targetX - sourceX;
            const dy = targetY - sourceY;
            const dr = Math.sqrt(dx * dx + dy * dy) * 2;
            return `M${sourceX},${sourceY}A${dr},${dr} 0 0,1 ${targetX},${targetY}`;
        });

    setTimeout(() => {
        d3Nodes.forEach(n => {
            if (typeof n.x === 'number' && typeof n.y === 'number' && !isNaN(n.x) && !isNaN(n.y)) {
                n.fx = null;
                n.fy = null;
            }
        });
    }, 500);
}

// =============================================================================
// UI Event Listeners
// =============================================================================

export function initStreamUI() {
    const streamModal = document.getElementById('stream-modal');
    if (!streamModal) {
        setTimeout(initStreamUI, 50);
        return;
    }

    const streamBtn = document.getElementById('stream-btn');
    const urlInput = document.getElementById('stream-url-input');
    const counterPositionSelect = document.getElementById('counter-position');
    const counterSizeSelect = document.getElementById('counter-size');

    // Generate OBS URL based on current settings
    function updateStreamUrl() {
        const user = Auth.getUser();
        const gameId = State.getGameId();

        if (!user || !gameId) {
            if (urlInput) urlInput.value = 'Load a game first';
            return;
        }

        const position = counterPositionSelect?.value || 'br';
        const size = counterSizeSelect?.value || 'md';

        const baseUrl = `${window.location.origin}/watch/${user.username}/${gameId}`;
        const params = new URLSearchParams({
            overlay: 'true',
            counter: position,
            size: size
        });

        if (urlInput) urlInput.value = `${baseUrl}?${params.toString()}`;
    }

    // Open modal and update URL
    if (streamBtn) {
        streamBtn.addEventListener('click', () => {
            updateStreamUrl();
            streamModal.classList.remove('hidden');
            streamModal.classList.add('visible');
        });
    }

    // Update URL when options change
    counterPositionSelect?.addEventListener('change', updateStreamUrl);
    counterSizeSelect?.addEventListener('change', updateStreamUrl);

    // Close modal buttons
    const closeModal = () => {
        streamModal.classList.remove('visible');
        streamModal.classList.add('hidden');
    };
    document.getElementById('close-stream-modal')?.addEventListener('click', closeModal);
    document.getElementById('close-stream-modal-btn')?.addEventListener('click', closeModal);

    // Copy URL button
    const copyUrlBtn = document.getElementById('copy-url-btn');
    if (copyUrlBtn) {
        copyUrlBtn.addEventListener('click', () => {
            if (urlInput) {
                urlInput.select();
                navigator.clipboard.writeText(urlInput.value).then(() => {
                    const originalText = copyUrlBtn.textContent;
                    copyUrlBtn.textContent = 'Copied!';
                    setTimeout(() => { copyUrlBtn.textContent = originalText; }, 2000);
                });
            }
        });
    }

    // Close on backdrop click
    streamModal.addEventListener('click', (e) => {
        if (e.target.id === 'stream-modal') {
            closeModal();
        }
    });
}

/**
 * Initialize Mod UI (button and modal).
 */
export function initModUI() {
    const modModal = document.getElementById('mod-config-modal');
    if (!modModal) {
        setTimeout(initModUI, 50);
        return;
    }

    const modBtn = document.getElementById('mod-btn');

    // Open modal when clicking the Mod button
    if (modBtn) {
        modBtn.addEventListener('click', () => {
            updateModConfig();
            modModal.classList.remove('hidden');
            modModal.classList.add('visible');
        });
    }
}

/**
 * Update the mod config content in the modal.
 */
function updateModConfig() {
    const content = document.getElementById('mod-config-content');
    if (!content) return;

    const user = Auth.getUser();
    const gameId = State.getGameId();

    if (!user || !gameId) {
        content.textContent = '# Load a game first';
        return;
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const serverUrl = `${wsProtocol}//${window.location.host}`;
    const modToken = user.modToken || '<your_mod_token>';

    content.textContent = `[server]
enabled = true
url = "${serverUrl}"
mod_token = "${modToken}"
game_id = "${gameId}"
auto_reconnect = true`;
}

/**
 * Update the mod connection indicator on the Mod button.
 * @param {boolean} connected - Whether the mod is connected
 */
export function updateModConnectionIndicator(connected) {
    const indicator = document.querySelector('#mod-btn .mod-btn-indicator');
    if (indicator) {
        if (connected) {
            indicator.classList.add('mod-connected');
        } else {
            indicator.classList.remove('mod-connected');
        }
    }
}

// =============================================================================
// State Event Subscriptions
// =============================================================================

State.subscribe('nodePositionsSaved', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

State.subscribe('viewportChanged', () => {
    syncViewport();
});

State.subscribe('selectionChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('nodeDiscovered', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

State.subscribe('nodeUndiscovered', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

State.subscribe('nodeTagsChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

State.subscribe('nodeSelected', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('searchMatched', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('searchCleared', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('frontierHighlightChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('tagFilterChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 50);
    }
});

State.subscribe('explorationModeChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), 200);
    }
});

State.subscribe('graphRenderCompleted', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

// =============================================================================
// Game WebSocket Protocol
// =============================================================================

/**
 * Connect as host to a game.
 * @param {string} gameId - Game UUID
 */
export async function connectAsHost(gameId) {
    const token = Auth.getToken();
    if (!token) {
        throw new Error('Not authenticated');
    }

    return new Promise((resolve, reject) => {
        const wsUrl = getWsUrl();
        gameWs = new WebSocket(`${wsUrl}/ws/host/${gameId}`);
        currentGameId = gameId;
        gameWsIsHost = true;

        let authResolved = false;

        gameWs.onopen = () => {
            // Send auth message
            gameWs.send(JSON.stringify({ type: 'auth', token }));
        };

        gameWs.onmessage = (event) => {
            const data = JSON.parse(event.data);

            // Handle ping/pong
            if (data.type === 'ping') {
                onGameWsPingReceived();
                gameWs.send(JSON.stringify({ type: 'pong' }));
                return;
            }

            // Auth response
            if (data.type === 'auth_ok') {
                startGameWsHeartbeatMonitoring();
                return;
            }

            if (data.type === 'auth_error') {
                authResolved = true;
                reject(new Error(data.message || 'Authentication failed'));
                gameWs.close();
                return;
            }

            // Game state received after auth
            if (data.type === 'game_state') {
                // Game state already loaded via API, this is for confirmation
                authResolved = true;
                State.setSyncState(true, true, gameId);
                resolve();
                return;
            }

            // Error from server
            if (data.type === 'error') {
                if (!authResolved) {
                    authResolved = true;
                    reject(new Error(data.message || 'Connection error'));
                } else {
                    Toast.error(data.message || 'WebSocket error');
                }
                return;
            }

            // Discovery from mod
            if (data.type === 'discovery') {
                handleDiscoveryFromServer(data.propagated, data.discovered_links);
                return;
            }

            // Mod connection status
            if (data.type === 'mod_connected') {
                updateModConnectionIndicator(true);
                return;
            }

            if (data.type === 'mod_disconnected') {
                updateModConnectionIndicator(false);
                return;
            }
        };

        gameWs.onerror = () => {
            stopGameWsHeartbeatMonitoring();
            if (!authResolved) {
                authResolved = true;
                reject(new Error('WebSocket connection failed'));
            }
        };

        gameWs.onclose = () => {
            stopGameWsHeartbeatMonitoring();
            if (State.isSyncConnected() && currentGameId === gameId) {
                handleGameWsDisconnect();
            }
        };
    });
}

/**
 * Connect as viewer to a game.
 * @param {string} gameId - Game UUID
 */
export async function connectAsViewer(gameId) {
    return new Promise((resolve, reject) => {
        const wsUrl = getWsUrl();
        gameWs = new WebSocket(`${wsUrl}/ws/viewer/${gameId}`);
        currentGameId = gameId;
        gameWsIsHost = false;

        let connected = false;

        gameWs.onopen = () => {
            startGameWsHeartbeatMonitoring();
            State.setSyncState(true, false, gameId);
            connected = true;
            resolve();
        };

        gameWs.onmessage = (event) => {
            const data = JSON.parse(event.data);

            // Handle ping/pong
            if (data.type === 'ping') {
                onGameWsPingReceived();
                gameWs.send(JSON.stringify({ type: 'pong' }));
                return;
            }

            // Error
            if (data.type === 'error') {
                if (!connected) {
                    reject(new Error(data.message || 'Connection error'));
                    gameWs.close();
                } else {
                    Toast.error(data.message || 'WebSocket error');
                }
                return;
            }

            // Waiting for host
            if (data.type === 'waiting') {
                // Host not connected yet
                return;
            }

            // Visual state from host
            if (data.type === 'visual_state') {
                if (State.isOverlayMode()) {
                    // Overlay mode: apply everything (selection, highlights, viewport, positions)
                    applySessionData(data.state);
                } else {
                    // Interactive viewer: only sync positions and discovery, ignore highlights/selection/viewport
                    applyPositionsAndDiscoveryOnly(data.state);
                }
                return;
            }

            // Positions update from host
            if (data.type === 'positions_update') {
                // All viewers sync positions
                applyPositionsFromServer(data.positions);
                return;
            }

            // Discovery from server
            if (data.type === 'discovery') {
                handleDiscoveryFromServer(data.propagated, data.discovered_links);
                return;
            }
        };

        gameWs.onerror = () => {
            stopGameWsHeartbeatMonitoring();
            if (!connected) {
                reject(new Error('WebSocket connection failed'));
            }
        };

        gameWs.onclose = () => {
            stopGameWsHeartbeatMonitoring();
            if (State.isSyncConnected() && currentGameId === gameId) {
                handleGameWsDisconnect();
            }
        };
    });
}

/**
 * Handle disconnection from game WebSocket - attempt reconnection.
 */
async function handleGameWsDisconnect() {
    // Reset mod connection indicator (we don't know the status while disconnected)
    updateModConnectionIndicator(false);

    // Prevent multiple concurrent reconnection attempts
    if (gameWsIsReconnecting) {
        return;
    }

    const gameId = currentGameId;
    if (!gameId) {
        State.setSyncState(false, false, null);
        return;
    }

    // Initialize reconnection timer on first attempt
    if (gameWsReconnectStartTime === null) {
        gameWsReconnectStartTime = Date.now();
    }

    // Check if we've exceeded the max reconnection duration
    const elapsed = Date.now() - gameWsReconnectStartTime;
    if (elapsed >= MAX_RECONNECT_DURATION) {
        console.log("Max reconnect duration reached (5 minutes)");
        gameWsReconnectStartTime = null;
        gameWsReconnectAttempts = 0;
        State.setSyncState(false, false, null);
        Toast.error('Connection lost. Please refresh the page.');
        return;
    }

    gameWsReconnectAttempts++;
    // Exponential backoff with cap
    const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, gameWsReconnectAttempts - 1), RECONNECT_MAX_DELAY);
    const remainingTime = Math.round((MAX_RECONNECT_DURATION - elapsed) / 1000);
    console.log(`Attempting game WS reconnect ${gameWsReconnectAttempts} in ${delay}ms (${remainingTime}s remaining)...`);
    Toast.warning(`Reconnecting... (${remainingTime}s remaining)`);

    gameWsIsReconnecting = true;

    setTimeout(async () => {
        // Check if game ID is still valid
        if (!currentGameId || currentGameId !== gameId) {
            gameWsIsReconnecting = false;
            return;
        }

        try {
            if (gameWsIsHost) {
                await connectAsHost(gameId);
            } else {
                await connectAsViewer(gameId);
            }
            // Success - reset reconnect state
            gameWsReconnectStartTime = null;
            gameWsReconnectAttempts = 0;
            gameWsIsReconnecting = false;
            Toast.show('Reconnected to server');
        } catch (e) {
            console.log('Reconnection attempt failed:', e.message);
            // Schedule next attempt
            gameWsIsReconnecting = false;
            handleGameWsDisconnect();
        }
    }, delay);
}

/**
 * Handle discovery messages from server (mod or other source).
 * Server is the source of truth - apply the full state it sends.
 */
function handleDiscoveryFromServer(propagated, discoveredLinks) {
    const explorationState = State.getExplorationState();
    if (!explorationState) return;

    let changed = false;

    // If server sent full discovered_links, use it directly (server is source of truth)
    if (discoveredLinks && Array.isArray(discoveredLinks)) {
        // Rebuild discovered nodes and links from server state
        const newDiscovered = new Set();
        const newDiscoveredLinks = new Set();

        for (const link of discoveredLinks) {
            const source = link.source;
            const target = link.target;
            newDiscovered.add(source);
            newDiscovered.add(target);
            newDiscoveredLinks.add(`${source}|${target}`);
        }

        // Check if anything changed
        if (newDiscovered.size !== explorationState.discovered.size ||
            newDiscoveredLinks.size !== explorationState.discoveredLinks.size) {
            changed = true;
        } else {
            // Size same, check contents
            for (const node of newDiscovered) {
                if (!explorationState.discovered.has(node)) {
                    changed = true;
                    break;
                }
            }
        }

        if (changed) {
            explorationState.discovered = newDiscovered;
            explorationState.discoveredLinks = newDiscoveredLinks;
        }
    } else if (propagated && Array.isArray(propagated)) {
        // Fallback: legacy mode without full state (shouldn't happen with updated server)
        for (const link of propagated) {
            const { source, target } = link;

            if (!explorationState.discovered.has(source)) {
                explorationState.discovered.add(source);
                changed = true;
            }
            if (!explorationState.discovered.has(target)) {
                explorationState.discovered.add(target);
                changed = true;
            }

            const linkId = `${source}|${target}`;
            if (!explorationState.discoveredLinks.has(linkId)) {
                explorationState.discoveredLinks.add(linkId);
                changed = true;
            }
        }
    }

    if (changed) {
        // Re-render graph to show newly discovered areas
        State.emit('graphNeedsRender', { preservePositions: true });
        Toast.show('New area discovered!');
    }
}

/**
 * Apply positions update from server (viewer side).
 */
function applyPositionsFromServer(positions) {
    if (!positions) return;

    for (const [nodeId, pos] of Object.entries(positions)) {
        State.saveNodePosition(nodeId, pos.x, pos.y);
    }

    // Update positions in DOM
    const simulation = State.getSimulation();
    if (simulation) {
        const d3Nodes = simulation.nodes();
        for (const node of d3Nodes) {
            const pos = positions[node.id];
            if (pos) {
                node.x = pos.x;
                node.y = pos.y;
                node.fx = pos.x;
                node.fy = pos.y;
            }
        }
        updatePositionsInDOM(d3Nodes);
    }
}

/**
 * Disconnect from current game.
 */
export function disconnect() {
    // Reset reconnection state
    gameWsIsReconnecting = false;
    gameWsReconnectStartTime = null;
    gameWsReconnectAttempts = 0;

    if (gameWs) {
        gameWs.close();
        gameWs = null;
    }
    currentGameId = null;

    State.setSyncState(false, false, null);
    lastSyncedViewport = null;
}
