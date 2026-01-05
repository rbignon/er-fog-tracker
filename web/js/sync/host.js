// ============================================================
// SYNC HOST - Host (streamer) WebSocket logic
// ============================================================

import { TIMING, WS } from '../constants.js';
import * as State from '../state.js';
import * as Auth from '../auth.js';
import { navigate } from '../router.js';
import {
    getWsUrl,
    getGameWs,
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
    setUpdateModConnectionIndicator,
} from './common.js';

// =============================================================================
// Host-specific State
// =============================================================================

let syncThrottle = null;
let isSyncing = false;

// =============================================================================
// Sync Logic (host only)
// =============================================================================

function syncState() {
    if (!State.isStreamerHost() || isSyncing) return;

    const gameWs = getGameWs();
    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

    // Throttle syncs to avoid flooding
    if (syncThrottle) return;

    syncThrottle = setTimeout(() => {
        syncThrottle = null;

        const ws = getGameWs();
        // Re-check connection state (may have changed during throttle delay)
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        isSyncing = true;
        try {
            const state = getFullSyncState();
            const message = JSON.stringify({
                type: 'visual_state',
                state,
            });
            ws.send(message);
        } catch (err) {
            console.error('[HOST SYNC] Failed to sync state:', err);
        } finally {
            isSyncing = false;
        }
    }, 50);
}

function syncViewport() {
    if (!State.isStreamerHost()) return;

    const gameWs = getGameWs();
    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

    // Viewport sync is handled by the general sync
    syncState();
}

function sendPositionsUpdate() {
    if (!State.isStreamerHost()) return;

    const gameWs = getGameWs();
    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;

    // Convert Map to plain object
    const nodePositions = State.getNodePositions();
    const positions = {};
    for (const [nodeId, pos] of nodePositions) {
        positions[nodeId] = { x: pos.x, y: pos.y };
    }

    gameWs.send(
        JSON.stringify({
            type: 'positions_update',
            positions,
        })
    );
}

// =============================================================================
// State Serialization (host only)
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

    const nodeElements = d3.selectAll('.node');
    const linkElements = d3.selectAll('.link');

    const graphData = State.getGraphData();
    const nodePositions = State.getNodePositions();
    const explorationState = State.getExplorationState();

    // Build nodes state from DOM (includes placeholders)
    const nodesState = {};
    nodeElements.each(function (d) {
        const nodeEl = d3.select(this);
        const pos = nodePositions.get(d.id);

        // For placeholders, get position from simulation data
        const x = d.x !== undefined ? d.x : pos ? pos.x : 0;
        const y = d.y !== undefined ? d.y : pos ? pos.y : 0;

        const tags = explorationState?.tags?.get(d.id) || [];
        const discovered = d.isPlaceholder ? false : explorationState?.discovered?.has(d.id) || false;

        nodesState[d.id] = {
            x: x,
            y: y,
            name: d.name || d.id, // Display name for viewer labels
            visible: nodeEl.style('display') !== 'none',
            highlighted: nodeEl.classed('highlighted'),
            dimmed: nodeEl.classed('dimmed'),
            frontierHighlight: nodeEl.classed('frontier-highlight'),
            accessHighlight: nodeEl.classed('access-highlight'),
            tagHighlighted: nodeEl.classed('tag-highlighted'),
            discovered: discovered,
            tags: tags,
            isBoss: d.isBoss || false,
            scaling: d.scaling || null,
            isPlaceholder: d.isPlaceholder || false,
            realId: d.realId || null,
            sourceNodeId: d.sourceNodeId || null,
        };
    });

    // Build links state from DOM (includes links to placeholders)
    const linksState = {};
    linkElements.each(function (d) {
        const linkEl = d3.select(this);
        const { sourceId, targetId } = State.getLinkEndpoints(d);

        linksState[`${sourceId}->${targetId}`] = {
            id: d.id || null,
            visible: linkEl.style('display') !== 'none',
            highlighted: linkEl.classed('highlighted'),
            dimmed: linkEl.classed('dimmed'),
            frontierHighlight: linkEl.classed('frontier-highlight'),
            type: d.type || null,
            oneWay: d.oneWay || false,
            // Store original target for placeholder links
            originalTarget: d.originalTarget || null,
            originalSource: d.originalSource || null,
        };
    });

    // Also include original graph nodes (undiscovered ones) for viewer to rebuild
    if (graphData && graphData.nodes) {
        graphData.nodes.forEach(n => {
            if (!nodesState[n.id]) {
                nodesState[n.id] = {
                    x: 0,
                    y: 0,
                    name: n.name || n.id, // Display name for viewer labels
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
                    isOriginalNode: true,
                };
            }
        });
    }

    // Also include original graph links for viewer to rebuild the graph
    if (graphData && graphData.links) {
        graphData.links.forEach(l => {
            const { sourceId, targetId } = State.getLinkEndpoints(l);
            const key = `${sourceId}->${targetId}`;
            // Only add if not already present (don't overwrite visual state)
            if (!linksState[key]) {
                linksState[key] = {
                    id: l.id || null,
                    visible: false,
                    highlighted: false,
                    dimmed: false,
                    frontierHighlight: false,
                    type: l.type || null,
                    oneWay: l.oneWay || false,
                    isOriginalLink: true,
                };
            }
        });
    }

    const transform = State.getCurrentZoomTransform();

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
            const linkIndex = State.getLinkIndex();
            const discoveredFromLinks = new Set();
            for (const linkUUID of explorationState.discoveredLinks) {
                // Use link index to get source/target from UUID
                const link = linkIndex?.byId.get(linkUUID);
                if (link) {
                    const { sourceId, targetId } = State.getLinkEndpoints(link);
                    if (nodeIds.has(sourceId)) discoveredFromLinks.add(sourceId);
                    if (nodeIds.has(targetId)) discoveredFromLinks.add(targetId);
                }
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
            hostHeight: window.innerHeight,
        },
        selectedNodeId: State.getSelectedNodeId() || null,
        frontierHighlightActive: State.isFrontierHighlightActive(),
        nodes: nodesState,
        links: linksState,
        // Note: discoveredLinks are NOT included here - server is source of truth
        // Discoveries are synced via 'discovery' messages from server/mod
        discoveredCount: discoveredCount,
        totalAreas: totalAreas,
    };
}

// =============================================================================
// UI (host only)
// =============================================================================

export function initStreamUI() {
    const streamModal = document.getElementById('stream-modal');
    if (!streamModal) {
        setTimeout(initStreamUI, TIMING.STREAM_UI_INIT);
        return;
    }

    const streamBtn = document.getElementById('stream-btn');
    const overlayUrlInput = document.getElementById('stream-url-input');
    const viewerUrlInput = document.getElementById('viewer-url-input');
    const counterPositionSelect = document.getElementById('counter-position');
    const counterSizeSelect = document.getElementById('counter-size');

    // Generate URLs based on current settings
    function updateUrls() {
        const user = Auth.getUser();
        const gameId = State.getGameId();

        if (!user || !gameId) {
            if (overlayUrlInput) overlayUrlInput.value = 'Load a game first';
            if (viewerUrlInput) viewerUrlInput.value = 'Load a game first';
            return;
        }

        const baseUrl = `${window.location.origin}/watch/${user.username}/${gameId}`;

        // Viewer URL (no overlay params)
        if (viewerUrlInput) viewerUrlInput.value = baseUrl;

        // OBS Overlay URL (with counter options)
        const position = counterPositionSelect?.value || 'br';
        const size = counterSizeSelect?.value || 'md';
        const params = new URLSearchParams({
            overlay: 'true',
            counter: position,
            size: size,
        });
        if (overlayUrlInput) overlayUrlInput.value = `${baseUrl}?${params.toString()}`;
    }

    // Open modal and update URLs
    if (streamBtn) {
        streamBtn.addEventListener('click', () => {
            updateUrls();
            streamModal.classList.remove('hidden');
            streamModal.classList.add('visible');
        });
    }

    // Update OBS URL when options change
    counterPositionSelect?.addEventListener('change', updateUrls);
    counterSizeSelect?.addEventListener('change', updateUrls);

    // Close modal
    const closeModal = () => {
        streamModal.classList.remove('visible');
        streamModal.classList.add('hidden');
    };
    document.getElementById('close-stream-modal')?.addEventListener('click', closeModal);

    // Helper to setup copy button
    function setupCopyButton(buttonId, inputElement) {
        const btn = document.getElementById(buttonId);
        if (btn && inputElement) {
            btn.addEventListener('click', () => {
                navigator.clipboard.writeText(inputElement.value).then(() => {
                    import('../toast.js').then(Toast => Toast.show('Copied to clipboard'));
                });
            });
        }
    }

    setupCopyButton('copy-url-btn', overlayUrlInput);
    setupCopyButton('copy-viewer-url-btn', viewerUrlInput);

    // Close on backdrop click
    streamModal.addEventListener('click', e => {
        if (e.target.id === 'stream-modal') {
            closeModal();
        }
    });
}

/**
 * Update the mod connection status indicator.
 * @param {boolean} connected - Whether the mod is connected
 */
export function updateModConnectionIndicator(connected) {
    const modStatus = document.getElementById('mod-status');
    if (modStatus) {
        if (connected) {
            modStatus.classList.add('mod-connected');
        } else {
            modStatus.classList.remove('mod-connected');
        }
    }
}

// Register mod indicator callback with common module
setUpdateModConnectionIndicator(updateModConnectionIndicator);

// =============================================================================
// State Event Subscriptions (host only)
// =============================================================================

State.subscribe('nodePositionsSaved', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        sendPositionsUpdate();
    }
});

State.subscribe('viewportChanged', () => {
    syncViewport();
});

State.subscribe('selectionChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
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

State.subscribe('nodeTagsChanged', ({ nodeId, tags }) => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        // Send tag_update to persist on server and broadcast to mod/viewers
        const gameWs = getGameWs();
        if (gameWs && gameWs.readyState === WebSocket.OPEN) {
            gameWs.send(
                JSON.stringify({
                    type: 'tag_update',
                    zone: nodeId,
                    tags: tags || [],
                })
            );
        }
        // Also sync visual state
        syncState();
    }
});

State.subscribe('nodeSelected', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
    }
});

State.subscribe('searchMatched', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
    }
});

State.subscribe('searchCleared', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
    }
});

State.subscribe('frontierHighlightChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
    }
});

State.subscribe('tagFilterChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE);
    }
});

State.subscribe('explorationModeChanged', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        setTimeout(() => syncState(), TIMING.SYNC_THROTTLE_SLOW);
    }
});

State.subscribe('graphRenderCompleted', () => {
    if (State.isSyncConnected() && State.isStreamerHost()) {
        syncState();
    }
});

// =============================================================================
// Host Connection
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
        const gameWs = new WebSocket(`${wsUrl}/ws/host/${gameId}`);
        setGameWs(gameWs);
        setCurrentGameId(gameId);
        setIsHost(true);

        let authResolved = false;

        gameWs.onopen = () => {
            // Send auth message
            gameWs.send(JSON.stringify({ type: 'auth', token }));
        };

        gameWs.onmessage = event => {
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

            // Game state received after auth (or reconnection)
            if (data.type === 'game_state') {
                // Apply discoveries from server (source of truth, may have changed during disconnect)
                // Pass isInitialSync=true to skip showing toasts for already-discovered zones
                if (data.state?.discovered_zone_links) {
                    handleDiscoveryFromServer([], data.state.discovered_zone_links, null, true);
                }
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
                    import('../toast.js').then(Toast => Toast.error(data.message || 'WebSocket error'));
                }
                return;
            }

            // Discovery from mod
            if (data.type === 'discovery') {
                // Use focus_target_id (zone_key) if available, fallback to focus_target
                const focusZoneId = data.focus_target_id || data.focus_target;
                handleDiscoveryFromServer(data.propagated, data.discovered_zone_links, data.stats, false, focusZoneId);
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

            // Tag update from mod
            if (data.type === 'tag_update') {
                handleTagUpdateFromServer(data.zone, data.tags);
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

        gameWs.onclose = event => {
            stopGameWsHeartbeatMonitoring();
            // Don't reconnect if session was replaced by another tab
            if (event.code === WS.CLOSE_SESSION_REPLACED) {
                console.log('[HOST] Session replaced by another tab, not reconnecting');
                import('../toast.js').then(Toast => Toast.warning('Session replaced by another browser tab'));
                State.setSyncState(false, false, null);
                navigate('/dashboard');
                return;
            }
            if (State.isSyncConnected() && getCurrentGameId() === gameId) {
                handleGameWsDisconnect();
            }
        };
    });
}
