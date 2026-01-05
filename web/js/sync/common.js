// ============================================================
// SYNC COMMON - Shared WebSocket state and utilities
// ============================================================

import * as State from '../state.js';
import * as Toast from '../toast.js';

// =============================================================================
// Configuration
// =============================================================================

export function getWsUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}`;
}

export const MAX_RECONNECT_DURATION = 5 * 60 * 1000; // 5 minutes total
export const RECONNECT_BASE_DELAY = 1000;
export const RECONNECT_MAX_DELAY = 30000; // Cap at 30 seconds between attempts

// =============================================================================
// Shared WebSocket State
// =============================================================================

let gameWs = null;
let currentGameId = null;
let gameWsReconnectAttempts = 0;
let gameWsReconnectStartTime = null;
let gameWsIsReconnecting = false;
let gameWsIsHost = false;

// Reconnection callbacks (set by host.js and viewer.js)
let reconnectAsHostFn = null;
let reconnectAsViewerFn = null;

// Getters and setters for shared state
export function getGameWs() {
    return gameWs;
}
export function setGameWs(ws) {
    gameWs = ws;
}
export function getCurrentGameId() {
    return currentGameId;
}
export function setCurrentGameId(id) {
    currentGameId = id;
}
export function isHost() {
    return gameWsIsHost;
}
export function setIsHost(value) {
    gameWsIsHost = value;
}
export function isReconnecting() {
    return gameWsIsReconnecting;
}

// Register reconnection functions (called from host.js and viewer.js)
export function registerReconnectFunctions(hostFn, viewerFn) {
    reconnectAsHostFn = hostFn;
    reconnectAsViewerFn = viewerFn;
}

// =============================================================================
// Heartbeat Monitoring
// =============================================================================

const HEARTBEAT_EXPECTED_INTERVAL = 15000; // Server sends ping every 15s
const HEARTBEAT_GRACE_PERIOD = 15000; // Allow 15s extra before considering dead
let lastGameWsPing = null;
let gameWsHeartbeatCheckInterval = null;

export function startGameWsHeartbeatMonitoring() {
    lastGameWsPing = Date.now();
    stopGameWsHeartbeatMonitoring(); // Clear any existing interval

    gameWsHeartbeatCheckInterval = setInterval(() => {
        if (!gameWs || gameWs.readyState !== WebSocket.OPEN) {
            stopGameWsHeartbeatMonitoring();
            return;
        }

        const timeSinceLastPing = Date.now() - lastGameWsPing;
        const timeout = HEARTBEAT_EXPECTED_INTERVAL + HEARTBEAT_GRACE_PERIOD;

        if (timeSinceLastPing > timeout) {
            console.log(
                `No server ping for game WS in ${Math.round(timeSinceLastPing / 1000)}s, connection likely dead`
            );
            // Force close to trigger reconnection
            gameWs.close();
            stopGameWsHeartbeatMonitoring();
        }
    }, 5000); // Check every 5 seconds
}

export function stopGameWsHeartbeatMonitoring() {
    if (gameWsHeartbeatCheckInterval) {
        clearInterval(gameWsHeartbeatCheckInterval);
        gameWsHeartbeatCheckInterval = null;
    }
}

export function onGameWsPingReceived() {
    lastGameWsPing = Date.now();
}

// =============================================================================
// Reconnection Logic
// =============================================================================

// Mod connection indicator update callback (set by host.js)
let updateModConnectionIndicatorFn = null;

export function setUpdateModConnectionIndicator(fn) {
    updateModConnectionIndicatorFn = fn;
}

export async function handleGameWsDisconnect() {
    // Reset mod connection indicator (we don't know the status while disconnected)
    if (updateModConnectionIndicatorFn) {
        updateModConnectionIndicatorFn(false);
    }

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
        console.log('Max reconnect duration reached (5 minutes)');
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
    console.log(
        `Attempting game WS reconnect ${gameWsReconnectAttempts} in ${delay}ms (${remainingTime}s remaining)...`
    );
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
                if (reconnectAsHostFn) {
                    await reconnectAsHostFn(gameId);
                }
            } else {
                if (reconnectAsViewerFn) {
                    await reconnectAsViewerFn(gameId);
                }
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

// =============================================================================
// Discovery and Tag Handling (shared by host and viewer)
// =============================================================================

/**
 * Handle tag update messages from server (mod or host).
 * Updates local tag state and triggers re-render.
 */
export function handleTagUpdateFromServer(zone, tags) {
    if (!zone) return;

    const explorationState = State.getExplorationState();
    if (!explorationState) return;

    // Update local tags without emitting (to avoid loop)
    const currentTags = explorationState.tags.get(zone) || [];
    const newTags = tags || [];

    // Check if tags actually changed
    if (JSON.stringify(currentTags) !== JSON.stringify(newTags)) {
        if (newTags.length > 0) {
            explorationState.tags.set(zone, newTags);
        } else {
            explorationState.tags.delete(zone);
        }

        // Save to local storage
        State.saveExplorationToStorage();

        // Trigger UI update
        State.emit('graphNeedsRender', { preservePositions: true });
    }
}

/**
 * Handle discovery messages from server (mod or other source).
 * Server is the source of truth - apply the full state it sends.
 * Server sends links with {zone_link_id} format - we resolve source/target via linkIndex.
 * @param {Array} propagated - Propagated links (with source/target already resolved)
 * @param {Array} discoveredZoneLinks - All discovered zone links (may only have zone_link_id)
 * @param {Object} [stats] - Discovery stats from server {discovered, total}
 * @param {boolean} [isInitialSync=false] - True for initial sync (don't show toasts)
 * @param {string} [focusTarget] - The zone to center on (destination of the traversal)
 */
export function handleDiscoveryFromServer(
    propagated,
    discoveredZoneLinks,
    stats,
    isInitialSync = false,
    focusTarget = null
) {
    const explorationState = State.getExplorationState();
    if (!explorationState) return;

    // Use linkIndex to resolve zone_link_id → source/target
    const linkIndex = State.getLinkIndex();

    let changed = false;
    let newlyDiscoveredTarget = null;
    const newlyDiscoveredZones = []; // Track all newly discovered zones

    // If server sent full discovered_zone_links, use it directly (server is source of truth)
    if (discoveredZoneLinks && Array.isArray(discoveredZoneLinks)) {
        // Rebuild discovered nodes and links from server state
        // Always include starting zone (same as server-side logic)
        const newDiscovered = new Set([State.getStartNodeId()]);
        const newDiscoveredLinks = new Set();

        for (const link of discoveredZoneLinks) {
            const linkId = link.zone_link_id || link.link_id;
            if (linkId) {
                newDiscoveredLinks.add(linkId);

                // Resolve source/target from linkIndex
                const linkData = linkIndex?.byId.get(linkId);
                if (linkData) {
                    const { sourceId, targetId } = State.getLinkEndpoints(linkData);
                    newDiscovered.add(sourceId);
                    newDiscovered.add(targetId);
                }
            }
        }

        // Find newly discovered zones (zones in new state but not in old state)
        for (const node of newDiscovered) {
            if (!explorationState.discovered.has(node)) {
                newlyDiscoveredZones.push(node);
            }
        }

        // Check if anything changed
        if (
            newDiscovered.size !== explorationState.discovered.size ||
            newDiscoveredLinks.size !== explorationState.discoveredLinks.size
        ) {
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
            // Use focusTarget from server if provided, otherwise fall back to first propagated target
            if (focusTarget) {
                newlyDiscoveredTarget = focusTarget;
            } else if (propagated && propagated.length > 0) {
                newlyDiscoveredTarget = propagated[0].target;
            }
            explorationState.discovered = newDiscovered;
            explorationState.discoveredLinks = newDiscoveredLinks;
        }
    } else if (propagated && Array.isArray(propagated)) {
        // Fallback: legacy mode without full state - use link index to find link UUIDs
        for (const link of propagated) {
            const { source, target } = link;

            if (!explorationState.discovered.has(source)) {
                explorationState.discovered.add(source);
                newlyDiscoveredZones.push(source);
                changed = true;
            }
            if (!explorationState.discovered.has(target)) {
                explorationState.discovered.add(target);
                newlyDiscoveredZones.push(target);
                changed = true;
                // First newly discovered target
                if (!newlyDiscoveredTarget) {
                    newlyDiscoveredTarget = target;
                }
            }

            // Find link UUID from endpoints using link index
            const linkIds = State.getLinkIdsByEndpoints(source, target);
            for (const linkId of linkIds) {
                if (!explorationState.discoveredLinks.has(linkId)) {
                    explorationState.discoveredLinks.add(linkId);
                    changed = true;
                }
            }
        }
    }

    if (changed) {
        // Update metadata stats - use server stats if provided (source of truth)
        const graphData = State.getGraphData();
        if (graphData?.metadata) {
            if (stats && stats.discovered !== undefined && stats.total !== undefined) {
                graphData.metadata.discoveryCount = stats.discovered;
                graphData.metadata.totalZones = stats.total;
            } else {
                // Fallback to local count
                graphData.metadata.discoveryCount = explorationState.discovered.size;
            }
        }

        // On host, select the newly discovered node and show its tooltip
        // But don't auto-select if frontier mode is active (to preserve frontier view)
        const shouldShowTooltip = State.isStreamerHost() && newlyDiscoveredTarget;
        if (shouldShowTooltip) {
            State.setSelectedNodeId(newlyDiscoveredTarget);
        }

        // Re-render graph to show newly discovered areas
        State.emit('graphNeedsRender', {
            preservePositions: true,
            centerOnNodeId: newlyDiscoveredTarget,
            showTooltipForNodeId: shouldShowTooltip ? newlyDiscoveredTarget : null,
        });

        // Show toast for each newly discovered zone (skip on initial sync)
        if (!isInitialSync) {
            const graphData = State.getGraphData();
            const nodeMap = graphData?.nodes ? new Map(graphData.nodes.map(n => [n.id, n])) : new Map();
            for (const zone of newlyDiscoveredZones) {
                const node = nodeMap.get(zone);
                const displayName = node?.name || zone;
                Toast.show(`Discovered: ${displayName}`, { type: 'info' });
            }
        }
    }
}

// =============================================================================
// Disconnect
// =============================================================================

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
}
