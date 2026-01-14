// ============================================================
// EXPLORATION MODE - Discovery, propagation, path finding
// ============================================================

import * as State from './state.js';
import * as Api from './api.js';

// ============================================================
// UI HELPERS
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
        tags: new Map(),
    });

    // Discover starting area and propagate through pre-existing connections
    discoverWithPreexisting(State.getStartNodeId(), null, null);
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
 * Load existing exploration state from storage.
 * Note: Call after setGraphData() so link index is available.
 *
 * @param {string} seed - The game seed to load
 * @returns {boolean} True if save was loaded, false if no save exists
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
            if (viaLink && viaLink.id) {
                State.discoverLinkById(viaLink.id);
            } else {
                State.discoverLink(fromNodeId, areaId);
            }
        }
        // Select the newly discovered node
        State.setSelectedNodeId(areaId);

        // Update last discovery indicator (host doesn't receive server broadcast)
        const graphData = State.getGraphData();
        const node = graphData?.nodes?.find(n => n.id === areaId);
        const displayName = node?.name || areaId;
        updateLastDiscoveryIndicator(displayName);

        State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: areaId });

        // Send to server - response will contain full state with back-propagation
        Api.createDiscovery(gameId, { source_id: fromNodeId, target_id: areaId, link_id: viaLink?.id })
            .then(response => {
                // Server response contains discovered_zone_links and stats - apply them
                if (response && response.discovered_zone_links) {
                    applyServerDiscoveryState(
                        response.discovered_zone_links,
                        response.discovery_count,
                        response.total_zones
                    );
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
            console.log(
                `[DISCOVERY] Back-propagation path:`,
                pathToSource.map(s => `${s.fromNodeId} → ${s.toNodeId}`)
            );
            for (const step of pathToSource) {
                discoverWithPreexisting(step.toNodeId, step.fromNodeId, step.link);
            }
        } else {
            console.warn(`[DISCOVERY] No path found from START to '${fromNodeId}'`);
        }
    }

    discoverWithPreexisting(areaId, fromNodeId, viaLink);

    // Update last discovery indicator (offline mode only - online mode updates via server response)
    const graphData = State.getGraphData();
    const node = graphData?.nodes?.find(n => n.id === areaId);
    const displayName = node?.name || areaId;
    updateLastDiscoveryIndicator(displayName);

    // Select the newly discovered node
    State.setSelectedNodeId(areaId);
    State.saveExplorationToStorage();
    State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: areaId });
}

/**
 * Apply discovery state from server response (server is source of truth).
 * Server sends links with {zone_link_id} format - we resolve source/target via linkIndex.
 * @param {Array} discoveredZoneLinks - List of discovered zone links from server
 * @param {number} [discoveryCount] - Discovery count from server (optional)
 * @param {number} [totalZones] - Total zones from server (optional)
 */
function applyServerDiscoveryState(discoveredZoneLinks, discoveryCount, totalZones) {
    if (!discoveredZoneLinks || !Array.isArray(discoveredZoneLinks)) return;

    const explorationState = State.getExplorationState();
    if (!explorationState) return;

    // Use linkIndex to resolve zone_link_id → source/target
    const linkIndex = State.getLinkIndex();

    // Rebuild state from server data
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

    // Check if exploration state changed
    const explorationChanged =
        newDiscovered.size !== explorationState.discovered.size ||
        newDiscoveredLinks.size !== explorationState.discoveredLinks.size;

    if (explorationChanged) {
        explorationState.discovered = newDiscovered;
        explorationState.discoveredLinks = newDiscoveredLinks;
        State.saveExplorationToStorage();
    }

    // Update stats from server (server is source of truth for stats)
    let statsChanged = false;
    if (discoveryCount !== undefined && totalZones !== undefined) {
        const graphData = State.getGraphData();
        if (graphData?.metadata) {
            if (graphData.metadata.discoveryCount !== discoveryCount || graphData.metadata.totalZones !== totalZones) {
                graphData.metadata.discoveryCount = discoveryCount;
                graphData.metadata.totalZones = totalZones;
                statsChanged = true;
            }
        }
    }

    // Re-render if anything changed
    if (explorationChanged || statsChanged) {
        State.emit('graphNeedsRender', { preservePositions: true });
    }
}

/**
 * Undiscover an area and all areas that become unreachable (except starting area)
 */
export function undiscoverArea(areaId) {
    if (areaId === State.getStartNodeId()) return;

    State.saveAllNodePositions();

    const graphData = State.getGraphData();
    const explorationState = State.getExplorationState();
    if (!graphData || !explorationState) return;

    const isOnline = State.getBackendMode() === 'online';
    const gameId = State.getGameId();

    // Online mode: delegate to server for source of truth
    if (isOnline && gameId) {
        // Optimistic update: perform local undiscovery for responsive UI
        performLocalUndiscovery(areaId, graphData, explorationState);
        State.saveExplorationToStorage();
        State.emit('graphNeedsRender', { preservePositions: true });

        // Send to server - response will contain authoritative state
        Api.undiscoverZone(gameId, areaId)
            .then(response => {
                // Server response contains discovered_zone_links and stats - apply them
                if (response && response.discovered_zone_links) {
                    applyServerDiscoveryState(
                        response.discovered_zone_links,
                        response.discovery_count,
                        response.total_zones
                    );
                }
            })
            .catch(err => console.error('Failed to persist undiscovery:', err));
        return;
    }

    // Offline mode: compute everything locally
    performLocalUndiscovery(areaId, graphData, explorationState);
    State.saveExplorationToStorage();
    State.emit('graphNeedsRender', { preservePositions: true });
}

/**
 * Perform local undiscovery logic (shared between online optimistic update and offline mode)
 */
function performLocalUndiscovery(areaId, graphData, explorationState) {
    // First, undiscover the requested node and its links
    State.undiscoverNode(areaId);
    State.undiscoverLinksForNode(areaId);

    // Find all nodes that are no longer reachable from START_NODE
    const reachableFromStart = findReachableNodes(State.getStartNodeId(), graphData.links, explorationState.discovered);

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
            const { sourceId, targetId } = State.getLinkEndpoints(link);

            // Can go FROM currentId TO target (following link direction)
            // BUT only if the link is discovered (or it's a preexisting link from a discovered node)
            if (sourceId === currentId && discoveredSet.has(targetId) && !reachable.has(targetId)) {
                const linkDiscovered =
                    State.isLinkDiscovered(sourceId, targetId) || State.isLinkDiscovered(targetId, sourceId);
                if (linkDiscovered) {
                    reachable.add(targetId);
                    queue.push(targetId);
                }
            }
            // Can go FROM target TO currentId only if link is NOT one-way AND link is discovered
            if (targetId === currentId && !link.oneWay && discoveredSet.has(sourceId) && !reachable.has(sourceId)) {
                const linkDiscovered =
                    State.isLinkDiscovered(sourceId, targetId) || State.isLinkDiscovered(targetId, sourceId);
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
 * @param {Object|null} viaLink - The link used to get here (to check if one-way or blocks propagation)
 */
function discoverWithPreexisting(areaId, fromNodeId, viaLink) {
    const explorationState = State.getExplorationState();
    const wasAlreadyDiscovered = explorationState.discovered.has(areaId);

    // If coming from another node via a specific link, record that link as discovered
    if (fromNodeId && viaLink && viaLink.id) {
        State.discoverLinkById(viaLink.id);
    } else if (fromNodeId) {
        // No specific link provided - discover one link between the nodes
        State.discoverLink(fromNodeId, areaId);
    }

    // If node was already discovered, we only needed to record the link
    if (wasAlreadyDiscovered) return;

    State.discoverNode(areaId);

    const graphData = State.getGraphData();
    if (!graphData) return;

    // If the link used to get here blocks propagation (e.g., conditional fog gate
    // like shortcut ladder), don't propagate through preexisting links from this area.
    // The player can see/use the exit but can't access the rest of the destination zone.
    if (viaLink && viaLink.blocksPropagation) {
        return;
    }

    // Find and follow pre-existing connections (respecting one-way)
    graphData.links.forEach(link => {
        if (link.type !== 'preexisting') return;

        const { sourceId, targetId } = State.getLinkEndpoints(link);

        // Can go FROM areaId TO target (following link direction)
        if (sourceId === areaId) {
            if (!explorationState.discovered.has(targetId)) {
                // Target not discovered - discover it recursively
                discoverWithPreexisting(targetId, areaId, link);
            } else if (link.id) {
                // Target already discovered - just record the preexisting link
                State.discoverLinkById(link.id);
            }
        }
        // Can go FROM target TO areaId only if link is NOT one-way
        else if (targetId === areaId && !link.oneWay) {
            if (!explorationState.discovered.has(sourceId)) {
                // Source not discovered - discover it recursively
                discoverWithPreexisting(sourceId, areaId, link);
            } else if (link.id) {
                // Source already discovered - just record the preexisting link
                State.discoverLinkById(link.id);
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

            const { sourceId, targetId } = State.getLinkEndpoints(link);

            if (sourceId === areaId) {
                if (!explorationState.discovered.has(targetId)) {
                    discoverWithPreexisting(targetId, areaId, link);
                } else if (link.id) {
                    // Both already discovered - ensure preexisting link is recorded
                    State.discoverLinkById(link.id);
                }
            } else if (targetId === areaId && !link.oneWay) {
                if (!explorationState.discovered.has(sourceId)) {
                    discoverWithPreexisting(sourceId, areaId, link);
                } else if (link.id) {
                    // Both already discovered - ensure preexisting link is recorded
                    State.discoverLinkById(link.id);
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
    if (nodeId === State.getStartNodeId()) return true;

    const explorationState = State.getExplorationState();
    const linkIndex = State.getLinkIndex();
    if (!explorationState || !linkIndex) return false;

    // BFS through discovered links
    const visited = new Set([State.getStartNodeId()]);
    const queue = [State.getStartNodeId()];

    while (queue.length > 0) {
        const current = queue.shift();

        // Check all discovered links for connections
        for (const linkUUID of explorationState.discoveredLinks) {
            const link = linkIndex.byId.get(linkUUID);
            if (!link) continue;

            const { sourceId, targetId } = State.getLinkEndpoints(link);
            let neighbor = null;

            // Can traverse in either direction (bidirectional links already have both indexed)
            if (sourceId === current && !visited.has(targetId)) {
                neighbor = targetId;
            } else if (targetId === current && !visited.has(sourceId)) {
                neighbor = sourceId;
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
    if (targetId === State.getStartNodeId()) return [];

    const graphData = State.getGraphData();
    const explorationState = State.getExplorationState();
    if (!graphData || !explorationState) return [];

    const nodeConnections = buildNodeConnectionsMap(graphData);

    // BFS with priority for discovered nodes
    const visited = new Set([State.getStartNodeId()]);
    const queue = [{ nodeId: State.getStartNodeId(), path: [] }];

    while (queue.length > 0) {
        const { nodeId: current, path } = queue.shift();
        const conns = nodeConnections.get(current);
        if (!conns) continue;

        // Split neighbors into discovered/undiscovered
        const discoveredNeighbors = [];
        const undiscoveredNeighbors = [];

        for (const { link, reversed } of conns.outgoing) {
            const { sourceId: linkSourceId, targetId: linkTargetId } = State.getLinkEndpoints(link);
            const neighborId = reversed ? linkSourceId : linkTargetId;

            if (visited.has(neighborId)) continue;

            const step = { fromNodeId: current, toNodeId: neighborId, link };

            if (explorationState.discovered.has(neighborId)) {
                discoveredNeighbors.push({ neighborId, step });
            } else {
                undiscoveredNeighbors.push({ neighborId, step });
            }
        }

        // Process discovered first, then undiscovered
        for (const { neighborId, step } of [...discoveredNeighbors, ...undiscoveredNeighbors]) {
            const newPath = [...path, step];

            if (neighborId === targetId) {
                return newPath;
            }

            visited.add(neighborId);
            // Insert discovered at front for priority
            if (explorationState.discovered.has(neighborId)) {
                queue.unshift({ nodeId: neighborId, path: newPath });
            } else {
                queue.push({ nodeId: neighborId, path: newPath });
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

    const isOnline = State.getBackendMode() === 'online';
    const gameId = State.getGameId();

    // BFS to find shortest path (using all nodes, not just discovered)
    // Track both nodes and the links used to reach them
    const visited = new Set([State.getStartNodeId()]);
    const queue = [[State.getStartNodeId(), [{ nodeId: State.getStartNodeId(), fromNodeId: null, viaLink: null }]]];

    while (queue.length > 0) {
        const [currentId, pathSteps] = queue.shift();

        if (currentId === targetId) {
            // Found the target - discover all nodes on the path with their links
            State.saveAllNodePositions();

            // Online mode: send to server, which handles back-propagation
            if (isOnline && gameId && pathSteps.length > 1) {
                // Find last step with fromNodeId to send to server
                const lastStep = pathSteps[pathSteps.length - 1];
                if (lastStep.fromNodeId) {
                    // Optimistic update
                    let discoveredCount = 0;
                    pathSteps.forEach(step => {
                        if (!State.isDiscovered(step.nodeId)) {
                            discoverWithPreexisting(step.nodeId, step.fromNodeId, step.viaLink);
                            discoveredCount++;
                        } else if (step.fromNodeId && step.viaLink && step.viaLink.id) {
                            State.discoverLinkById(step.viaLink.id);
                        } else if (step.fromNodeId) {
                            State.discoverLink(step.fromNodeId, step.nodeId);
                        }
                    });

                    // Select the target node
                    State.setSelectedNodeId(targetId);
                    State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: targetId });
                    showDiscoveryNotification(discoveredCount, targetId);

                    // Send to server - server will back-propagate
                    Api.createDiscovery(gameId, {
                        source_id: lastStep.fromNodeId,
                        target_id: targetId,
                        link_id: lastStep.viaLink?.id,
                    })
                        .then(response => {
                            if (response && response.discovered_zone_links) {
                                applyServerDiscoveryState(
                                    response.discovered_zone_links,
                                    response.discovery_count,
                                    response.total_zones
                                );
                            }
                        })
                        .catch(err => console.error('Failed to persist discovery:', err));
                    return;
                }
            }

            // Offline mode: compute everything locally
            let discoveredCount = 0;
            pathSteps.forEach(step => {
                if (!State.isDiscovered(step.nodeId)) {
                    discoverWithPreexisting(step.nodeId, step.fromNodeId, step.viaLink);
                    discoveredCount++;
                } else if (step.fromNodeId && step.viaLink && step.viaLink.id) {
                    // Node already discovered, but still record the link
                    State.discoverLinkById(step.viaLink.id);
                } else if (step.fromNodeId) {
                    State.discoverLink(step.fromNodeId, step.nodeId);
                }
            });

            // Select the target node
            State.setSelectedNodeId(targetId);
            State.saveExplorationToStorage();
            State.emit('graphNeedsRender', { preservePositions: true, centerOnNodeId: targetId });
            showDiscoveryNotification(discoveredCount, targetId);
            return;
        }

        // Find all neighbors (respecting one-way links)
        graphData.links.forEach(link => {
            const { sourceId: linkSourceId, targetId: linkTargetId } = State.getLinkEndpoints(link);

            let neighborId = null;
            // Can always follow link direction
            if (linkSourceId === currentId) {
                neighborId = linkTargetId;
            }
            // Can go backwards only if link is NOT one-way
            else if (linkTargetId === currentId && !link.oneWay) {
                neighborId = linkSourceId;
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
    if (targetNodeId === State.getStartNodeId()) {
        return { nodes: new Set([State.getStartNodeId()]), links: new Set() };
    }

    const graphData = State.getGraphData();
    if (!graphData) return { nodes: new Set(), links: new Set() };

    // Build node connections map
    const nodeConnections = buildNodeConnectionsMap(graphData);

    // In exploration mode, only traverse through discovered nodes AND discovered links
    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();
    const canTraverseNode = nodeId => {
        if (!explorationMode) return true;
        return explorationState.discovered.has(nodeId);
    };
    const canTraverseLink = (fromId, toId) => {
        if (!explorationMode) return true;
        return State.isLinkDiscovered(fromId, toId) || State.isLinkDiscovered(toId, fromId);
    };

    const visited = new Set([State.getStartNodeId()]);
    const queue = [[State.getStartNodeId(), [], []]]; // [nodeId, pathNodes, pathLinks]

    while (queue.length > 0) {
        const [currentId, pathNodes, pathLinks] = queue.shift();
        const conns = nodeConnections.get(currentId);
        if (!conns) continue;

        // Follow outgoing links (includes reverse direction for bidirectional links)
        for (const { link, reversed } of conns.outgoing) {
            // Determine the actual target based on whether this is a reversed link
            const { sourceId: linkSourceId, targetId: linkTargetId } = State.getLinkEndpoints(link);
            const neighborId = reversed ? linkSourceId : linkTargetId;

            if (visited.has(neighborId)) continue;
            // Must be able to traverse both the link AND the node (unless it's the target)
            if (!canTraverseLink(currentId, neighborId)) continue;
            if (neighborId !== targetNodeId && !canTraverseNode(neighborId)) continue;
            visited.add(neighborId);

            const newPathNodes = [...pathNodes, currentId];
            const newPathLinks = [...pathLinks, link];

            if (neighborId === targetNodeId) {
                return {
                    nodes: new Set([...newPathNodes, neighborId]),
                    links: new Set(newPathLinks),
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

    // In exploration mode, only traverse through discovered nodes AND discovered links
    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();
    const canTraverseNode = nodeId => {
        if (!explorationMode) return true;
        return explorationState.discovered.has(nodeId);
    };
    const canTraverseLink = (fromId, toId) => {
        if (!explorationMode) return true;
        return State.isLinkDiscovered(fromId, toId) || State.isLinkDiscovered(toId, fromId);
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
            const { sourceId, targetId } = State.getLinkEndpoints(link);
            const neighborId = reversed ? sourceId : targetId;

            if (visitedNodes.has(neighborId)) continue;

            // In exploration mode, stop at undiscovered links or nodes
            if (!canTraverseLink(currentId, neighborId)) continue;
            if (!canTraverseNode(neighborId)) continue;

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
        const { sourceId, targetId } = State.getLinkEndpoints(link);

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
 *
 * Properties:
 * - incoming/outgoing: arrays of { link, reversed } for directional traversal
 * - degree: total directional connections (used for path finding)
 * - distinctLinks: count of unique links (a bidirectional link counts as 1, used for hub detection)
 */
export function buildNodeConnectionsMap(graphData) {
    const nodeConnections = new Map();

    graphData.nodes.forEach(n => {
        nodeConnections.set(n.id, { incoming: [], outgoing: [], degree: 0, distinctLinks: 0 });
    });

    // Build set of all explicit link pairs to avoid duplicating bidirectional links
    // when both directions are already present in the data
    const explicitLinkPairs = new Set();
    graphData.links.forEach(l => {
        const { sourceId, targetId } = State.getLinkEndpoints(l);
        explicitLinkPairs.add(`${sourceId}|${targetId}`);
    });

    graphData.links.forEach(l => {
        const { sourceId, targetId } = State.getLinkEndpoints(l);
        const isSelfLoop = sourceId === targetId;

        const sourceConns = nodeConnections.get(sourceId);
        const targetConns = nodeConnections.get(targetId);

        // Forward direction: source -> target
        if (sourceConns) {
            sourceConns.outgoing.push({ link: l, reversed: false });
            sourceConns.degree++;
            sourceConns.distinctLinks++; // Each link counts once for source
        }
        if (targetConns && !isSelfLoop) {
            targetConns.incoming.push({ link: l, reversed: false });
            targetConns.degree++;
            targetConns.distinctLinks++; // Each link counts once for target
        }

        // Reverse direction for bidirectional links: target -> source
        // But only if no explicit reverse link already exists in the data
        const hasExplicitReverse = explicitLinkPairs.has(`${targetId}|${sourceId}`);
        if (!l.oneWay && !isSelfLoop && !hasExplicitReverse) {
            if (targetConns) {
                targetConns.outgoing.push({ link: l, reversed: true });
                targetConns.degree++;
                // Don't increment distinctLinks - already counted above
            }
            if (sourceConns) {
                sourceConns.incoming.push({ link: l, reversed: true });
                sourceConns.degree++;
                // Don't increment distinctLinks - already counted above
            }
        }
    });

    return nodeConnections;
}

/**
 * Show discovery notification
 */
function showDiscoveryNotification(count, targetId) {
    let notification = document.getElementById('discovery-notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'discovery-notification';
        document.body.appendChild(notification);
    }

    // Look up display name from graph data
    const graphData = State.getGraphData();
    const node = graphData?.nodes?.find(n => n.id === targetId);
    const displayName = node?.name || targetId;

    notification.textContent = `✓ ${count} area${count > 1 ? 's' : ''} discovered on path to "${displayName}"`;
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
