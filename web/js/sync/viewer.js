// ============================================================
// SYNC VIEWER - Viewer WebSocket logic
// ============================================================

import { TIMING } from '../constants.js';
import * as State from '../state.js';
import * as PositionManager from '../positionManager.js';
import {
    getWsUrl,
    setGameWs,
    getCurrentGameId,
    setCurrentGameId,
    setIsHost,
    startGameWsHeartbeatMonitoring,
    stopGameWsHeartbeatMonitoring,
    onGameWsPingReceived,
    handleGameWsDisconnect,
    handleDiscoveryFromServer,
    handleTagUpdateFromServer,
} from './common.js';

// =============================================================================
// Viewer-specific State
// =============================================================================

let lastSyncedViewport = null;
let isRenderingGraph = false;
let lastReceivedVisualState = null; // Store last visual state from host for viewer restoration

// URL parameters for viewer options
const urlParams = new URLSearchParams(window.location.search);
// Counter position: off, tl, tr, bl, br (default), t, b, l, r (centered on edge)
const counterPosition = urlParams.get('counter') || 'br';
// Counter size: sm (small), md (medium, default), lg (large), xl (extra-large)
const counterSize = urlParams.get('size') || 'md';

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
    console.log('Building graph from session data...');

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
            name: nodeState.name || id, // Display name from sync data
            isBoss: nodeState.isBoss || false,
            scaling: nodeState.scaling || null,
            x: nodeState.x,
            y: nodeState.y,
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
                id: linkState.id || null,
                source: source,
                target: target,
                type: linkState.type || 'fog',
                oneWay: linkState.oneWay || false,
            });
        }
    }

    // Restore discovered links from sync data
    if (data.discoveredLinks && Array.isArray(data.discoveredLinks)) {
        data.discoveredLinks.forEach(linkId => {
            // Filter out null/undefined linkIds
            if (linkId) {
                explorationState.discoveredLinks.add(linkId);
            }
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

    const svg = d3.select('#graph-container svg');
    const g = svg.select('g');

    if (!svg.node() || !g.node()) {
        setTimeout(() => applyViewport(vp), TIMING.VIEWPORT_APPLY_DELAY);
        return;
    }

    if (
        lastSyncedViewport &&
        Math.abs(vp.x - lastSyncedViewport.x) <= 1 &&
        Math.abs(vp.y - lastSyncedViewport.y) <= 1 &&
        Math.abs(vp.k - lastSyncedViewport.k) <= 0.01
    ) {
        return;
    }

    lastSyncedViewport = { x: vp.x, y: vp.y, k: vp.k };

    if (
        !vp ||
        typeof vp.x !== 'number' ||
        typeof vp.y !== 'number' ||
        typeof vp.k !== 'number' ||
        isNaN(vp.x) ||
        isNaN(vp.y) ||
        isNaN(vp.k) ||
        !isFinite(vp.x) ||
        !isFinite(vp.y) ||
        !isFinite(vp.k) ||
        vp.k <= 0
    ) {
        console.warn('Invalid viewport data:', vp);
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
        console.warn('Invalid calculated viewport transform:', { x, y, vp });
        return;
    }

    const transform = d3.zoomIdentity.translate(x, y).scale(vp.k);
    State.setCurrentZoomTransform(transform);

    g.transition().duration(300).attr('transform', `translate(${x},${y}) scale(${vp.k})`);
}

function applyVisualState(data) {
    if (!data.nodes) return false;

    // Store the received state for viewer restoration
    lastReceivedVisualState = data;

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
        if (
            nodeState.x !== undefined &&
            nodeState.y !== undefined &&
            !isNaN(nodeState.x) &&
            !isNaN(nodeState.y) &&
            isFinite(nodeState.x) &&
            isFinite(nodeState.y)
        ) {
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

        if (
            simNode &&
            nodeState.x !== undefined &&
            nodeState.y !== undefined &&
            !isNaN(nodeState.x) &&
            !isNaN(nodeState.y) &&
            isFinite(nodeState.x) &&
            isFinite(nodeState.y)
        ) {
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

    // NOTE: We do NOT sync discoveredLinks from host's visual_state.
    // Server is the source of truth for discoveries. Discoveries are synced via
    // handleDiscoveryFromServer when the server sends 'discovery' or 'game_state' messages.

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
            // Update both state and checkbox - the event handler in ui.js
            // will update the checkbox and skip recalculation for viewers
            State.setFrontierHighlightActive(data.frontierHighlightActive);
        }
    }

    applyVisualClasses(data);

    if (positionsChanged) {
        PositionManager.updatePositionsInDOM(d3Nodes);
    }

    // Only sync selection in overlay mode - interactive viewers control their own selection
    if (data.selectedNodeId !== undefined && State.isOverlayMode()) {
        State.setSelectedNodeId(data.selectedNodeId || null);
    }

    return false;
}

function applyVisualClasses(data) {
    // In overlay mode, use host's selection; in interactive mode, use local selection
    const selectedId = State.isOverlayMode() ? data.selectedNodeId || null : State.getSelectedNodeId();

    d3.selectAll('.node').each(function (d) {
        const nodeState = data.nodes?.[d.id];
        const node = d3.select(this);

        if (nodeState) {
            node.classed('highlighted', nodeState.highlighted || false)
                .classed('dimmed', nodeState.dimmed || false)
                .classed('frontier-highlight', nodeState.frontierHighlight || false)
                .classed('access-highlight', nodeState.accessHighlight || false)
                .classed('tag-highlighted', nodeState.tagHighlighted || false);
        }

        // Handle selection separately - apply even if nodeState doesn't exist
        node.classed('viewer-selected', d.id === selectedId);

        // Show selection ring in viewer modes (overlay or interactive)
        if (d.id === selectedId && State.isViewerMode()) {
            if (node.select('.selection-ring').empty()) {
                const circle = node.select('circle');
                const r = parseFloat(circle.attr('r')) || 7;
                node.insert('circle', 'circle')
                    .attr('class', 'selection-ring')
                    .attr('r', r + 8);
            }
        } else {
            node.select('.selection-ring').remove();
        }
    });

    if (data.links) {
        d3.selectAll('.link').each(function (d) {
            const { sourceId, targetId } = State.getLinkEndpoints(d);
            const linkKey = `${sourceId}->${targetId}`;
            const linkState = data.links[linkKey];
            if (linkState) {
                d3.select(this)
                    .classed('highlighted', linkState.highlighted || false)
                    .classed('dimmed', linkState.dimmed || false)
                    .classed('frontier-highlight', linkState.frontierHighlight || false);
            }
        });
    }

    // Update viewer discovery counter
    updateViewerDiscoveryCounter(data);
}

/**
 * Restore the last visual state received from host.
 * Used by overlay mode when clearing local selection to restore frontier highlights.
 */
export function restoreLastVisualState() {
    if (lastReceivedVisualState) {
        applyVisualClasses(lastReceivedVisualState);
    }
}

// =============================================================================
// Discovery Counter (OBS overlay only)
// =============================================================================

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

// =============================================================================
// Viewer Connection
// =============================================================================

/**
 * Connect as viewer to a game.
 * @param {string} gameId - Game UUID
 */
export async function connectAsViewer(gameId) {
    return new Promise((resolve, reject) => {
        const wsUrl = getWsUrl();
        const gameWs = new WebSocket(`${wsUrl}/ws/viewer/${gameId}`);
        setGameWs(gameWs);
        setCurrentGameId(gameId);
        setIsHost(false);

        let connected = false;

        gameWs.onopen = () => {
            startGameWsHeartbeatMonitoring();
            State.setSyncState(true, false, gameId);
            connected = true;
            resolve();
        };

        gameWs.onmessage = event => {
            const data = JSON.parse(event.data);

            // Handle ping/pong
            if (data.type === 'ping') {
                onGameWsPingReceived();
                try {
                    gameWs.send(JSON.stringify({ type: 'pong' }));
                } catch (err) {
                    console.error('[VIEWER] Failed to send pong:', err);
                }
                return;
            }

            // Error
            if (data.type === 'error') {
                if (!connected) {
                    reject(new Error(data.message || 'Connection error'));
                    gameWs.close();
                } else {
                    import('../toast.js').then(Toast => Toast.error(data.message || 'WebSocket error'));
                }
                return;
            }

            // Waiting for host
            if (data.type === 'waiting') {
                // Host not connected yet
                return;
            }

            // Game state from server (source of truth for discoveries)
            // Pass isInitialSync=true to skip showing toasts for already-discovered zones
            if (data.type === 'game_state') {
                if (data.state?.discovered_zone_links) {
                    handleDiscoveryFromServer([], data.state.discovered_zone_links, null, true);
                }
                return;
            }

            // Visual state from host
            if (data.type === 'visual_state') {
                if (State.isOverlayMode()) {
                    // Overlay mode: apply everything (selection, highlights, viewport, positions)
                    applySessionData(data.state);
                }
                // Interactive viewers ignore visual_state entirely.
                // They receive data via dedicated messages: positions_update, discovery, tag_update
                return;
            }

            // Positions update from host
            if (data.type === 'positions_update') {
                // All viewers sync positions
                PositionManager.applyFromServer(data.positions);
                return;
            }

            // Discovery from server
            if (data.type === 'discovery') {
                // Use focus_target_id (zone_key) if available, fallback to focus_target
                const focusZoneId = data.focus_target_id || data.focus_target;
                handleDiscoveryFromServer(data.propagated, data.discovered_zone_links, data.stats, false, focusZoneId);
                return;
            }

            // Tag update from host/mod
            if (data.type === 'tag_update') {
                handleTagUpdateFromServer(data.zone_id, data.tags);
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
            if (State.isSyncConnected() && getCurrentGameId() === gameId) {
                handleGameWsDisconnect();
            }
        };
    });
}
