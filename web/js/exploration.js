// ============================================================
// EXPLORATION MODE - Discovery, propagation, path finding
// ============================================================

import * as State from './state.js';
import * as Api from './api.js';

// ============================================================
// DISCOVERY LOGIC
// ============================================================

/**
 * Initialize exploration state with starting area
 */
export function initExplorationState() {
    State.setExplorationState({
        discovered: new Set(),
        discoveredLinks: new Set(),
        tags: new Map()
    });

    // Discover starting area and propagate through pre-existing connections
    discoverWithPreexisting(State.START_NODE, null, null);
    State.saveExplorationToStorage();
}

/**
 * Reset exploration state to initial
 */
export function resetExplorationState() {
    State.clearExplorationStorage();
    initExplorationState();
    State.emit('explorationReset');
}

/**
 * Load existing exploration state from storage
 */
export function loadExplorationState(seed) {
    const saved = State.loadExplorationFromStorage(seed);
    if (saved) {
        State.setExplorationState(saved);
        return true;
    }
    return false;
}

/**
 * Migrate legacy saves that don't have discoveredLinks.
 * For backwards compatibility, all links between discovered nodes are marked as discovered.
 * Should be called after graphData is loaded.
 */
export function migrateDiscoveredLinks() {
    const graphData = State.getGraphData();
    const explorationState = State.getExplorationState();
    if (!graphData || !explorationState) return;

    // If discoveredLinks already has entries, no migration needed
    if (explorationState.discoveredLinks && explorationState.discoveredLinks.size > 0) return;

    // Mark all links between discovered nodes as discovered
    let migrated = false;
    graphData.links.forEach(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;

        if (explorationState.discovered.has(sourceId) && explorationState.discovered.has(targetId)) {
            // Both nodes discovered - mark link as discovered in both directions (if bidirectional)
            State.discoverLink(sourceId, targetId, !link.oneWay);
            migrated = true;
        }
    });

    if (migrated) {
        State.saveExplorationToStorage();
        console.log('Migrated legacy save: marked existing links as discovered');
    }
}

/**
 * Discover an area via a specific link and propagate through pre-existing connections.
 *
 * In online mode: delegates to server for propagation logic (server is source of truth).
 * In offline mode: computes propagation locally.
 *
 * @param {string} areaId - The area to discover
 * @param {string|null} fromNodeId - The node from which we're discovering (for link tracking)
 * @param {Object|null} viaLink - The link used to discover (to check if one-way)
 */
export function discoverArea(areaId, fromNodeId = null, viaLink = null) {
    State.saveAllNodePositions();

    const isOnline = State.getBackendMode() === 'online';
    const gameId = State.getGameId();

    // Online mode with fromNodeId: delegate to server
    if (isOnline && fromNodeId && gameId) {
        // Optimistic update: just mark the direct link as discovered for responsive UI
        // Server will send back the full state with back-propagation
        const explorationState = State.getExplorationState();
        if (explorationState) {
            explorationState.discovered.add(areaId);
            const isBidirectional = !viaLink || !viaLink.oneWay;
            State.discoverLink(fromNodeId, areaId, isBidirectional);
        }
        State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: areaId });

        // Send to server - response will contain full state with back-propagation
        Api.createDiscovery(gameId, { source: fromNodeId, target: areaId })
            .then(response => {
                // Server response contains discovered_links - apply it
                if (response && response.discovered_links) {
                    applyServerDiscoveryState(response.discovered_links);
                }
            })
            .catch(err => console.error('Failed to persist discovery:', err));
        return;
    }

    // Offline mode: compute everything locally
    // Back-propagation: if source is not accessible from START, discover path to it first
    if (fromNodeId && !isAccessibleFromStart(fromNodeId)) {
        console.log(`[DISCOVERY] Source '${fromNodeId}' not accessible from START, back-propagating`);
        const pathToSource = findPathPrioritizingDiscovered(fromNodeId);
        if (pathToSource.length > 0) {
            console.log(`[DISCOVERY] Back-propagation path:`, pathToSource.map(s => `${s.fromNodeId} → ${s.toNodeId}`));
            for (const step of pathToSource) {
                discoverWithPreexisting(step.toNodeId, step.fromNodeId, step.link);
            }
        } else {
            console.warn(`[DISCOVERY] No path found from START to '${fromNodeId}'`);
        }
    }

    discoverWithPreexisting(areaId, fromNodeId, viaLink);
    State.saveExplorationToStorage();
    State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: areaId });
}

/**
 * Apply discovery state from server response (server is source of truth).
 */
function applyServerDiscoveryState(discoveredLinks) {
    if (!discoveredLinks || !Array.isArray(discoveredLinks)) return;

    const explorationState = State.getExplorationState();
    if (!explorationState) return;

    // Rebuild state from server data
    const newDiscovered = new Set();
    const newDiscoveredLinks = new Set();

    for (const link of discoveredLinks) {
        newDiscovered.add(link.source);
        newDiscovered.add(link.target);
        newDiscoveredLinks.add(`${link.source}|${link.target}`);
    }

    // Check if state actually changed
    const changed = newDiscovered.size !== explorationState.discovered.size ||
        newDiscoveredLinks.size !== explorationState.discoveredLinks.size;

    if (changed) {
        explorationState.discovered = newDiscovered;
        explorationState.discoveredLinks = newDiscoveredLinks;
        State.saveExplorationToStorage();
        State.emit('graphNeedsRender', { preservePositions: true });
    }
}

/**
 * Undiscover an area and all areas that become unreachable (except starting area)
 */
export function undiscoverArea(areaId) {
    if (areaId === State.START_NODE) return;

    State.saveAllNodePositions();

    const graphData = State.getGraphData();
    const explorationState = State.getExplorationState();
    if (!graphData || !explorationState) return;

    // First, undiscover the requested node and its links
    State.undiscoverNode(areaId);
    State.undiscoverLinksForNode(areaId);

    // Find all nodes that are no longer reachable from START_NODE
    const reachableFromStart = findReachableNodes(State.START_NODE, graphData.links, explorationState.discovered);

    // Undiscover all nodes that are no longer reachable
    const toUndiscover = [];
    explorationState.discovered.forEach(nodeId => {
        if (!reachableFromStart.has(nodeId)) {
            toUndiscover.push(nodeId);
        }
    });

    toUndiscover.forEach(nodeId => {
        State.undiscoverNode(nodeId);
        State.undiscoverLinksForNode(nodeId);
    });

    State.saveExplorationToStorage();
    State.emit('graphNeedsRender', { preservePositions: true });
}

/**
 * Find all nodes reachable from a starting node through discovered nodes AND discovered links
 */
function findReachableNodes(startNodeId, links, discoveredSet) {
    const explorationState = State.getExplorationState();
    const reachable = new Set([startNodeId]);
    const queue = [startNodeId];

    while (queue.length > 0) {
        const currentId = queue.shift();

        links.forEach(link => {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;

            // Can go FROM currentId TO target (following link direction)
            // BUT only if the link is discovered (or it's a preexisting link from a discovered node)
            if (sourceId === currentId && discoveredSet.has(targetId) && !reachable.has(targetId)) {
                const linkDiscovered = State.isLinkDiscovered(sourceId, targetId) || State.isLinkDiscovered(targetId, sourceId);
                if (linkDiscovered) {
                    reachable.add(targetId);
                    queue.push(targetId);
                }
            }
            // Can go FROM target TO currentId only if link is NOT one-way AND link is discovered
            if (targetId === currentId && !link.oneWay && discoveredSet.has(sourceId) && !reachable.has(sourceId)) {
                const linkDiscovered = State.isLinkDiscovered(sourceId, targetId) || State.isLinkDiscovered(targetId, sourceId);
                if (linkDiscovered) {
                    reachable.add(sourceId);
                    queue.push(sourceId);
                }
            }
        });
    }

    return reachable;
}

/**
 * Internal: discover area and recursively discover pre-existing connections
 * @param {string} areaId - The area to discover
 * @param {string|null} fromNodeId - The node from which we came (to record the link)
 * @param {Object|null} viaLink - The link used to get here (to check if one-way)
 */
function discoverWithPreexisting(areaId, fromNodeId, viaLink) {
    const explorationState = State.getExplorationState();
    const wasAlreadyDiscovered = explorationState.discovered.has(areaId);

    // If coming from another node, record the link as discovered
    if (fromNodeId) {
        // Determine if the link is bidirectional
        const isBidirectional = !viaLink || !viaLink.oneWay;
        State.discoverLink(fromNodeId, areaId, isBidirectional);
    }

    // If node was already discovered, we only needed to record the link
    if (wasAlreadyDiscovered) return;

    State.discoverNode(areaId);

    const graphData = State.getGraphData();
    if (!graphData) return;

    // Find and follow pre-existing connections (respecting one-way)
    graphData.links.forEach(link => {
        if (link.type !== 'preexisting') return;

        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;

        // Can go FROM areaId TO target (following link direction)
        if (sourceId === areaId) {
            if (!explorationState.discovered.has(targetId)) {
                // Target not discovered - discover it recursively
                discoverWithPreexisting(targetId, areaId, link);
            } else {
                // Target already discovered - just record the preexisting link
                const isBidirectional = !link.oneWay;
                State.discoverLink(areaId, targetId, isBidirectional);
            }
        }
        // Can go FROM target TO areaId only if link is NOT one-way
        else if (targetId === areaId && !link.oneWay) {
            if (!explorationState.discovered.has(sourceId)) {
                // Source not discovered - discover it recursively
                discoverWithPreexisting(sourceId, areaId, link);
            } else {
                // Source already discovered - just record the preexisting link
                State.discoverLink(areaId, sourceId, true); // bidirectional since we're going backwards
            }
        }
    });
}

/**
 * Propagate discovery through pre-existing connections for all discovered areas
 * (called after graph data is loaded to sync state)
 */
export function propagatePreexistingDiscoveries() {
    const explorationState = State.getExplorationState();
    const graphData = State.getGraphData();
    if (!explorationState || !graphData) return;

    const toPropagate = Array.from(explorationState.discovered);
    toPropagate.forEach(areaId => {
        graphData.links.forEach(link => {
            if (link.type !== 'preexisting') return;

            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;

            if (sourceId === areaId) {
                if (!explorationState.discovered.has(targetId)) {
                    discoverWithPreexisting(targetId, areaId, link);
                } else {
                    // Both already discovered - ensure preexisting link is recorded
                    const isBidirectional = !link.oneWay;
                    State.discoverLink(areaId, targetId, isBidirectional);
                }
            } else if (targetId === areaId && !link.oneWay) {
                if (!explorationState.discovered.has(sourceId)) {
                    discoverWithPreexisting(sourceId, areaId, link);
                } else {
                    // Both already discovered - ensure preexisting link is recorded
                    State.discoverLink(areaId, sourceId, true);
                }
            }
        });
    });
}

// ============================================================
// PATH FINDING
// ============================================================

/**
 * Check if a node is accessible from START_NODE via discovered links.
 */
function isAccessibleFromStart(nodeId) {
    if (nodeId === State.START_NODE) return true;

    const explorationState = State.getExplorationState();
    if (!explorationState) return false;

    // BFS through discovered links
    const visited = new Set([State.START_NODE]);
    const queue = [State.START_NODE];

    while (queue.length > 0) {
        const current = queue.shift();

        // Check all discovered links for connections
        for (const linkId of explorationState.discoveredLinks) {
            const [src, tgt] = linkId.split('|');
            let neighbor = null;

            // Can traverse in either direction
            if (src === current && !visited.has(tgt)) {
                neighbor = tgt;
            } else if (tgt === current && !visited.has(src)) {
                neighbor = src;
            }

            if (neighbor) {
                if (neighbor === nodeId) return true;
                visited.add(neighbor);
                queue.push(neighbor);
            }
        }
    }

    return false;
}

/**
 * Find path from START_NODE to target, prioritizing discovered nodes.
 * Returns array of {fromNodeId, toNodeId, link} for each step.
 */
function findPathPrioritizingDiscovered(targetId) {
    if (targetId === State.START_NODE) return [];

    const graphData = State.getGraphData();
    const explorationState = State.getExplorationState();
    if (!graphData || !explorationState) return [];

    const nodeConnections = buildNodeConnectionsMap(graphData);

    // BFS with priority for discovered nodes
    const visited = new Set([State.START_NODE]);
    const queue = [{nodeId: State.START_NODE, path: []}];

    while (queue.length > 0) {
        const {nodeId: current, path} = queue.shift();
        const conns = nodeConnections.get(current);
        if (!conns) continue;

        // Split neighbors into discovered/undiscovered
        const discoveredNeighbors = [];
        const undiscoveredNeighbors = [];

        for (const {link, reversed} of conns.outgoing) {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetNodeId = typeof link.target === 'object' ? link.target.id : link.target;
            const neighborId = reversed ? sourceId : targetNodeId;

            if (visited.has(neighborId)) continue;

            const step = {fromNodeId: current, toNodeId: neighborId, link};

            if (explorationState.discovered.has(neighborId)) {
                discoveredNeighbors.push({neighborId, step});
            } else {
                undiscoveredNeighbors.push({neighborId, step});
            }
        }

        // Process discovered first, then undiscovered
        for (const {neighborId, step} of [...discoveredNeighbors, ...undiscoveredNeighbors]) {
            const newPath = [...path, step];

            if (neighborId === targetId) {
                return newPath;
            }

            visited.add(neighborId);
            // Insert discovered at front for priority
            if (explorationState.discovered.has(neighborId)) {
                queue.unshift({nodeId: neighborId, path: newPath});
            } else {
                queue.push({nodeId: neighborId, path: newPath});
            }
        }
    }

    return []; // No path found
}

/**
 * Discover all nodes on the path from Starting Area to target
 */
export function discoverPathTo(targetId) {
    const graphData = State.getGraphData();
    if (!graphData) return;

    // BFS to find shortest path (using all nodes, not just discovered)
    // Track both nodes and the links used to reach them
    const visited = new Set([State.START_NODE]);
    const queue = [[State.START_NODE, [{ nodeId: State.START_NODE, fromNodeId: null, viaLink: null }]]];

    while (queue.length > 0) {
        const [currentId, pathSteps] = queue.shift();

        if (currentId === targetId) {
            // Found the target - discover all nodes on the path with their links
            State.saveAllNodePositions();

            let discoveredCount = 0;
            pathSteps.forEach(step => {
                if (!State.isDiscovered(step.nodeId)) {
                    discoverWithPreexisting(step.nodeId, step.fromNodeId, step.viaLink);
                    discoveredCount++;
                } else if (step.fromNodeId) {
                    // Node already discovered, but still record the link
                    const isBidirectional = !step.viaLink || !step.viaLink.oneWay;
                    State.discoverLink(step.fromNodeId, step.nodeId, isBidirectional);
                }
            });

            State.saveExplorationToStorage();
            State.emit('graphNeedsRender', { preservePositions: true });
            showDiscoveryNotification(discoveredCount, targetId);
            return;
        }

        // Find all neighbors (respecting one-way links)
        graphData.links.forEach(link => {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetNodeId = typeof link.target === 'object' ? link.target.id : link.target;

            let neighborId = null;
            // Can always follow link direction
            if (sourceId === currentId) {
                neighborId = targetNodeId;
            }
            // Can go backwards only if link is NOT one-way
            else if (targetNodeId === currentId && !link.oneWay) {
                neighborId = sourceId;
            }

            if (neighborId && !visited.has(neighborId)) {
                visited.add(neighborId);
                queue.push([neighborId, [...pathSteps, { nodeId: neighborId, fromNodeId: currentId, viaLink: link }]]);
            }
        });
    }

    console.warn('No path found to', targetId);
}

/**
 * Find path from start node to target using BFS
 */
export function findPathFromStart(targetNodeId) {
    if (targetNodeId === State.START_NODE) {
        return { nodes: new Set([State.START_NODE]), links: new Set() };
    }
    
    const graphData = State.getGraphData();
    if (!graphData) return { nodes: new Set(), links: new Set() };
    
    // Build node connections map
    const nodeConnections = buildNodeConnectionsMap(graphData);
    
    // In exploration mode, only traverse through discovered nodes
    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();
    const canTraverse = (nodeId) => {
        if (!explorationMode) return true;
        return explorationState.discovered.has(nodeId);
    };
    
    const visited = new Set([State.START_NODE]);
    const queue = [[State.START_NODE, [], []]]; // [nodeId, pathNodes, pathLinks]

    while (queue.length > 0) {
        const [currentId, pathNodes, pathLinks] = queue.shift();
        const conns = nodeConnections.get(currentId);
        if (!conns) continue;

        // Follow outgoing links (includes reverse direction for bidirectional links)
        for (const { link, reversed } of conns.outgoing) {
            // Determine the actual target based on whether this is a reversed link
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;
            const neighborId = reversed ? sourceId : targetId;

            if (visited.has(neighborId)) continue;
            if (neighborId !== targetNodeId && !canTraverse(neighborId)) continue;
            visited.add(neighborId);

            const newPathNodes = [...pathNodes, currentId];
            const newPathLinks = [...pathLinks, link];

            if (neighborId === targetNodeId) {
                return {
                    nodes: new Set([...newPathNodes, neighborId]),
                    links: new Set(newPathLinks)
                };
            }

            queue.push([neighborId, newPathNodes, newPathLinks]);
        }
    }

    return { nodes: new Set(), links: new Set() };
}

/**
 * Follow linear path from a node (subway line behavior)
 * In exploration mode, stops at undiscovered nodes (frontier boundary)
 */
export function followLinearPath(startNodeId) {
    const graphData = State.getGraphData();
    if (!graphData) return { nodes: new Set([startNodeId]), links: new Set() };

    // In exploration mode, only traverse through discovered nodes
    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();
    const canTraverse = (nodeId) => {
        if (!explorationMode) return true;
        return explorationState.discovered.has(nodeId);
    };

    const nodeConnections = buildNodeConnectionsMap(graphData);
    const visitedNodes = new Set([startNodeId]);
    const visitedLinks = new Set();
    const queue = [startNodeId];

    while (queue.length > 0) {
        const currentId = queue.shift();
        const conns = nodeConnections.get(currentId);
        if (!conns) continue;

        // Only need to check outgoing - bidirectional links are included in both directions
        for (const { link, reversed } of conns.outgoing) {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;
            const neighborId = reversed ? sourceId : targetId;

            if (visitedNodes.has(neighborId)) continue;

            // In exploration mode, stop at undiscovered nodes
            if (!canTraverse(neighborId)) continue;

            visitedLinks.add(link);
            visitedNodes.add(neighborId);

            // Continue following if not a hub
            const neighborConns = nodeConnections.get(neighborId);
            if (neighborConns && neighborConns.degree < 3) {
                queue.push(neighborId);
            }
        }
    }

    return { nodes: visitedNodes, links: visitedLinks };
}

// ============================================================
// NODE STATUS
// ============================================================

/**
 * Get exploration status for a node
 */
export function getNodeExplorationStatus(nodeId, links) {
    if (!State.isExplorationMode()) {
        return { visible: true, discovered: true, accessible: true };
    }
    
    const explorationState = State.getExplorationState();
    const isDiscovered = explorationState.discovered.has(nodeId);
    
    if (isDiscovered) {
        return { visible: true, discovered: true, accessible: true };
    }
    
    // Check if accessible (can reach from a discovered node)
    const isAccessible = links.some(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        
        // Link goes FROM discovered TO nodeId
        if (sourceId !== nodeId && targetId === nodeId && explorationState.discovered.has(sourceId)) {
            return true;
        }
        // Link goes FROM nodeId TO discovered, but only if NOT one-way
        if (sourceId === nodeId && targetId !== nodeId && explorationState.discovered.has(targetId) && !link.oneWay) {
            return true;
        }
        
        return false;
    });
    
    return { visible: isAccessible, discovered: false, accessible: isAccessible };
}

// ============================================================
// HELPERS
// ============================================================

/**
 * Build a map of node connections from graph data
 * For bidirectional links (oneWay: false), adds connections in both directions
 * Each connection entry includes { link, reversed } to indicate if it's the reverse direction
 */
export function buildNodeConnectionsMap(graphData) {
    const nodeConnections = new Map();

    graphData.nodes.forEach(n => {
        nodeConnections.set(n.id, { incoming: [], outgoing: [], degree: 0 });
    });

    // Build set of all explicit link pairs to avoid duplicating bidirectional links
    // when both directions are already present in the data
    const explicitLinkPairs = new Set();
    graphData.links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        explicitLinkPairs.add(`${sourceId}|${targetId}`);
    });

    graphData.links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        const isSelfLoop = sourceId === targetId;

        const sourceConns = nodeConnections.get(sourceId);
        const targetConns = nodeConnections.get(targetId);

        // Forward direction: source -> target
        if (sourceConns) {
            sourceConns.outgoing.push({ link: l, reversed: false });
            sourceConns.degree++;
        }
        if (targetConns && !isSelfLoop) {
            targetConns.incoming.push({ link: l, reversed: false });
            targetConns.degree++;
        }

        // Reverse direction for bidirectional links: target -> source
        // But only if no explicit reverse link already exists in the data
        const hasExplicitReverse = explicitLinkPairs.has(`${targetId}|${sourceId}`);
        if (!l.oneWay && !isSelfLoop && !hasExplicitReverse) {
            if (targetConns) {
                targetConns.outgoing.push({ link: l, reversed: true });
                targetConns.degree++;
            }
            if (sourceConns) {
                sourceConns.incoming.push({ link: l, reversed: true });
                sourceConns.degree++;
            }
        }
    });

    return nodeConnections;
}

/**
 * Compute one-way property on links
 *
 * Logic:
 * - Preexisting links: one-way if no reverse link exists in the data
 * - Random links: one-way only if marked as isInherentlyOneWay (teleports, warps, etc.)
 *   Otherwise assumed bidirectional (fog gates can be traversed both ways)
 */
export function computeOneWayLinks(links) {
    if (!links || links.length === 0) return;

    // Build set of all link pairs for reverse lookup
    const linkPairs = new Set();
    links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        linkPairs.add(`${sourceId}|${targetId}`);
    });

    links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
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
 * Show discovery notification
 */
function showDiscoveryNotification(count, targetName) {
    let notification = document.getElementById('discovery-notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'discovery-notification';
        document.body.appendChild(notification);
    }
    
    notification.textContent = `✓ ${count} area${count > 1 ? 's' : ''} discovered on path to "${targetName}"`;
    notification.classList.add('visible');
    
    setTimeout(() => {
        notification.classList.remove('visible');
    }, 3000);
}

/**
 * Toggle a tag on a node
 */
export function toggleTag(nodeId, tagId) {
    const newTags = State.toggleNodeTag(nodeId, tagId);
    State.saveExplorationToStorage();
    State.emit('nodeTagsUpdated', { nodeId, tags: newTags });
    return newTags;
}
