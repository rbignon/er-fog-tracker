// ============================================================
// POSITION MANAGER - Centralized node position handling
// ============================================================

import * as State from './state.js';

// ============================================================
// HELPER FUNCTIONS
// ============================================================

/**
 * Simple hash function for deterministic positioning of placeholder nodes.
 * @param {string} str - String to hash
 * @returns {number} Positive integer hash
 */
function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = (hash << 5) - hash + char;
        hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash);
}

// ============================================================
// POSITION RESTORATION
// ============================================================

/**
 * Restore node positions from saved state and initialize new nodes.
 * Handles three categories of nodes:
 * 1. Non-placeholder nodes with saved positions - restore from state
 * 2. Placeholder nodes - position near their source node with deterministic offset
 * 3. New nodes without saved positions - position near connected neighbors
 *
 * @param {Array} nodes - Array of node objects to restore positions for
 * @param {Array} links - Array of link objects (used to find neighbors for new nodes)
 */
export function restore(nodes, links) {
    const nodePositions = State.getNodePositions();

    // First pass: restore known positions for non-placeholder nodes
    nodes.forEach(node => {
        if (node.isPlaceholder) return; // Handle placeholders separately

        const savedPos = nodePositions.get(node.id);
        if (
            savedPos &&
            typeof savedPos.x === 'number' &&
            typeof savedPos.y === 'number' &&
            !isNaN(savedPos.x) &&
            !isNaN(savedPos.y) &&
            isFinite(savedPos.x) &&
            isFinite(savedPos.y)
        ) {
            node.x = savedPos.x;
            node.y = savedPos.y;
            node.fx = savedPos.x;
            node.fy = savedPos.y;
        }
    });

    // Second pass: position placeholder nodes near their source node with deterministic offset
    nodes.forEach(node => {
        if (!node.isPlaceholder) return;

        const sourceNode = nodes.find(n => n.id === node.sourceNodeId);
        if (
            sourceNode &&
            typeof sourceNode.x === 'number' &&
            typeof sourceNode.y === 'number' &&
            !isNaN(sourceNode.x) &&
            !isNaN(sourceNode.y)
        ) {
            // Use a hash of the placeholder ID for deterministic positioning
            const hash = hashString(node.id);
            const angle = (hash % 360) * (Math.PI / 180);
            const distance = 80 + (hash % 40); // 80-120 pixels away

            node.x = sourceNode.x + Math.cos(angle) * distance;
            node.y = sourceNode.y + Math.sin(angle) * distance;
        } else {
            // Fallback: random position
            node.x = window.innerWidth / 2 + (Math.random() - 0.5) * 200;
            node.y = window.innerHeight / 2 + (Math.random() - 0.5) * 200;
        }
    });

    // Third pass: initialize other new nodes near neighbors
    nodes.forEach(node => {
        if (node.isPlaceholder) return;
        if (node.x !== undefined && !isNaN(node.x) && !isNaN(node.y)) return;

        const connectedLink = links?.find(l => {
            const { sourceId, targetId } = State.getLinkEndpoints(l);
            return sourceId === node.id || targetId === node.id;
        });

        if (connectedLink) {
            const { sourceId, targetId } = State.getLinkEndpoints(connectedLink);
            const neighborId = sourceId === node.id ? targetId : sourceId;
            const neighborNode = nodes.find(n => n.id === neighborId);

            if (
                neighborNode &&
                typeof neighborNode.x === 'number' &&
                typeof neighborNode.y === 'number' &&
                !isNaN(neighborNode.x) &&
                !isNaN(neighborNode.y)
            ) {
                node.x = neighborNode.x + (Math.random() - 0.5) * 100;
                node.y = neighborNode.y + (Math.random() - 0.5) * 100;
            }
        }

        if (node.x === undefined || isNaN(node.x) || isNaN(node.y)) {
            node.x = window.innerWidth / 2 + (Math.random() - 0.5) * 200;
            node.y = window.innerHeight / 2 + (Math.random() - 0.5) * 200;
        }
    });
}

// ============================================================
// SERVER SYNC
// ============================================================

/**
 * Apply positions received from server (for viewer sync).
 * Updates both state storage and simulation nodes.
 *
 * @param {Object} positions - Map of nodeId -> {x, y} positions from server
 */
export function applyFromServer(positions) {
    if (!positions) return;

    // Save positions to state
    for (const [nodeId, pos] of Object.entries(positions)) {
        State.saveNodePosition(nodeId, pos.x, pos.y);
    }

    // Update simulation nodes if available
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

        // Update positions in DOM with transition
        updatePositionsInDOM(d3Nodes);
    }
}

/**
 * Update node and link positions in the DOM with smooth transition.
 * @param {Array} d3Nodes - Array of D3 simulation nodes
 */
export function updatePositionsInDOM(d3Nodes) {
    // Assumes d3 is available globally
    d3.selectAll('.node')
        .transition()
        .duration(300)
        .attr('transform', d => {
            const x = typeof d.x === 'number' && !isNaN(d.x) && isFinite(d.x) ? d.x : 0;
            const y = typeof d.y === 'number' && !isNaN(d.y) && isFinite(d.y) ? d.y : 0;
            return `translate(${x},${y})`;
        });

    d3.selectAll('.link')
        .transition()
        .duration(300)
        .attr('d', d => {
            const sourceX = typeof d.source.x === 'number' && !isNaN(d.source.x) ? d.source.x : 0;
            const sourceY = typeof d.source.y === 'number' && !isNaN(d.source.y) ? d.source.y : 0;
            const targetX = typeof d.target.x === 'number' && !isNaN(d.target.x) ? d.target.x : 0;
            const targetY = typeof d.target.y === 'number' && !isNaN(d.target.y) ? d.target.y : 0;
            const dx = targetX - sourceX;
            const dy = targetY - sourceY;
            const dr = Math.sqrt(dx * dx + dy * dy) * 2;
            return `M${sourceX},${sourceY}A${dr},${dr} 0 0,1 ${targetX},${targetY}`;
        });

    // Unfreeze nodes after transition completes
    setTimeout(() => {
        d3Nodes.forEach(n => {
            if (typeof n.x === 'number' && typeof n.y === 'number' && !isNaN(n.x) && !isNaN(n.y)) {
                n.fx = null;
                n.fy = null;
            }
        });
    }, 500);
}
