// ============================================================
// GRAPH - D3.js rendering, simulation, interactions
// ============================================================

import { extractRequiredItemFromDescription, parseRequiredItemZones } from './parser.js';
import * as State from './state.js';
import * as Exploration from './exploration.js';

// Track which tags are selected for filtering
let selectedTagFilters = new Set();

// ============================================================
// RENDER GRAPH
// ============================================================

export function renderGraph(preservePositions = false) {
    const graphData = State.getGraphData();
    if (!graphData) return;

    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();

    // Propagate discoveries through pre-existing connections
    if (explorationMode && explorationState) {
        Exploration.propagatePreexistingDiscoveries();
        State.saveExplorationToStorage();
    }

    // Clear previous graph
    d3.select("#graph-container svg").selectAll("*").remove();

    const width = window.innerWidth;
    const height = window.innerHeight;

    const svg = d3.select("#graph-container svg")
        .attr("viewBox", [0, 0, width, height]);

    // Create container for zoom
    const container = svg.append("g");

    // Save current transform BEFORE setting up zoom (svg.call(zoom) triggers the handler with identity)
    const savedTransform = preservePositions ? State.getCurrentZoomTransform() : null;

    // Zoom behavior
    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
            container.attr("transform", event.transform);
            State.setCurrentZoomTransform(event.transform);
            State.emit('viewportChanged', event.transform);
        });

    svg.call(zoom);

    // Restore zoom if preserving positions (use savedTransform captured before svg.call(zoom))
    if (preservePositions && savedTransform &&
        isFinite(savedTransform.x) && isFinite(savedTransform.y) && isFinite(savedTransform.k)) {
        svg.call(zoom.transform, savedTransform);
    }
    
    // Arrow markers (defs)
    svg.append("defs");
    
    // Process data (deep clone to avoid mutation)
    const nodes = graphData.nodes.map(d => ({...d}));
    const links = graphData.links.map(d => ({...d}));

    // Create node map
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // Build connections map
    const nodeConnections = Exploration.buildNodeConnectionsMap({ nodes, links });

    // Update stats
    document.getElementById("area-count").textContent = nodes.length;
    document.getElementById("random-count").textContent = links.filter(l => l.type === "random").length;
    document.getElementById("preexisting-count").textContent = links.filter(l => l.type === "preexisting").length;

    // Update discovered stats (exploration mode only)
    // Use server-calculated stats if available, otherwise calculate locally
    const discoveredStat = document.getElementById("discovered-stat");
    if (explorationMode && explorationState) {
        let discoveredCount, totalAreas;

        if (graphData.metadata?.discoveryCount !== undefined && graphData.metadata?.totalZones !== undefined) {
            // Use server-calculated stats (most accurate)
            discoveredCount = graphData.metadata.discoveryCount;
            totalAreas = graphData.metadata.totalZones;
        } else {
            // Fallback: calculate locally from discovered links (using link UUIDs)
            totalAreas = nodes.length;
            const nodeIds = new Set(nodes.map(n => n.id));
            const linkIndex = State.getLinkIndex();
            const discoveredFromLinks = new Set();
            for (const linkUUID of explorationState.discoveredLinks || []) {
                // Use link index to get source/target from UUID
                const link = linkIndex?.byId.get(linkUUID);
                if (link) {
                    const source = typeof link.source === 'object' ? link.source.id : link.source;
                    const target = typeof link.target === 'object' ? link.target.id : link.target;
                    if (nodeIds.has(source)) discoveredFromLinks.add(source);
                    if (nodeIds.has(target)) discoveredFromLinks.add(target);
                }
            }
            discoveredCount = discoveredFromLinks.size;
        }

        const percent = totalAreas > 0 ? Math.round((discoveredCount / totalAreas) * 100) : 0;

        document.getElementById("discovered-count").textContent = discoveredCount;
        document.getElementById("total-areas").textContent = totalAreas;
        document.getElementById("discovered-percent").textContent = percent;
        discoveredStat.classList.remove("hidden");
    } else {
        discoveredStat.classList.add("hidden");
    }

    // Show/hide "Requires Key Item" legend
    const hasRequiredItems = links.some(l => l.requiredItemFrom);
    document.getElementById("legend-requires-item").classList.toggle('hidden', !hasRequiredItems);

    // Update seed display
    if (graphData.metadata && graphData.metadata.seed) {
        const label = graphData.metadata.label;
        document.getElementById("seed-info").textContent = label
            ? `${label} — Seed: ${graphData.metadata.seed}`
            : `Seed: ${graphData.metadata.seed}`;
    } else {
        document.getElementById("seed-info").textContent = 'Spoiler Log Visualizer';
    }

    // Update button visibility
    updateButtonVisibility(explorationMode);

    // Mark hub nodes (3+ distinct links - bidirectional links count as 1)
    nodes.forEach(n => {
        const conns = nodeConnections.get(n.id);
        n.isHub = conns && conns.distinctLinks >= 3;
    });

    document.getElementById("hub-count").textContent = nodes.filter(n => n.isHub).length;

    // Compute exploration status for each node
    nodes.forEach(d => {
        d.explorationStatus = Exploration.getNodeExplorationStatus(d.id, links);
    });

    // In exploration mode, create placeholder nodes for undiscovered areas
    // Each link to an undiscovered node gets its own "???" placeholder
    let visibleNodes, visibleLinks;
    const placeholderMap = new Map(); // Maps placeholder ID to real node ID

    if (explorationMode && explorationState) {
        const discoveredNodes = nodes.filter(d => explorationState.discovered.has(d.id));
        const placeholderNodes = [];
        const processedLinks = [];

        links.forEach(link => {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;
            const sourceDiscovered = explorationState.discovered.has(sourceId);
            const targetDiscovered = explorationState.discovered.has(targetId);

            if (sourceDiscovered && targetDiscovered) {
                // Both nodes discovered - but is THIS SPECIFIC link discovered?
                // We must check the link's UUID directly, not just if any link between
                // endpoints is discovered. Otherwise, parallel links (e.g., a preexisting
                // link AND a random link between same nodes) would all show as discovered
                // when only one of them was actually traversed.
                const isThisLinkDiscovered = link.id && explorationState.discoveredLinks.has(link.id);

                if (isThisLinkDiscovered) {
                    // Link is discovered: show normal link
                    processedLinks.push({...link});
                } else {
                    // Link NOT discovered: create placeholder(s) for undiscovered link
                    // Forward direction: source -> target (always possible)
                    const placeholderIdForward = `???_${sourceId}_${targetId}`;
                    placeholderMap.set(placeholderIdForward, targetId);

                    if (!placeholderNodes.find(n => n.id === placeholderIdForward)) {
                        const realNode = nodeMap.get(targetId);
                        placeholderNodes.push({
                            id: placeholderIdForward,
                            realId: targetId,
                            isPlaceholder: true,
                            isUndiscoveredLink: true, // Mark as undiscovered link to existing node
                            isBoss: realNode?.isBoss || false,
                            scaling: realNode?.scaling || null,
                            sourceNodeId: sourceId
                        });
                    }

                    processedLinks.push({
                        ...link,
                        target: placeholderIdForward,
                        originalTarget: targetId
                    });

                    // Backward direction: target -> source (only if bidirectional)
                    if (!link.oneWay) {
                        const placeholderIdBackward = `???_${targetId}_${sourceId}`;
                        placeholderMap.set(placeholderIdBackward, sourceId);

                        if (!placeholderNodes.find(n => n.id === placeholderIdBackward)) {
                            const realNode = nodeMap.get(sourceId);
                            placeholderNodes.push({
                                id: placeholderIdBackward,
                                realId: sourceId,
                                isPlaceholder: true,
                                isUndiscoveredLink: true,
                                isBoss: realNode?.isBoss || false,
                                scaling: realNode?.scaling || null,
                                sourceNodeId: targetId
                            });
                        }

                        processedLinks.push({
                            ...link,
                            source: placeholderIdBackward,
                            originalSource: sourceId
                        });
                    }
                }
            } else if (sourceDiscovered && !targetDiscovered) {
                // Source discovered, target not: create placeholder for target
                const placeholderId = `???_${sourceId}_${targetId}`;
                placeholderMap.set(placeholderId, targetId);

                // Create placeholder node if not exists
                if (!placeholderNodes.find(n => n.id === placeholderId)) {
                    const realNode = nodeMap.get(targetId);
                    placeholderNodes.push({
                        id: placeholderId,
                        realId: targetId,
                        isPlaceholder: true,
                        isBoss: realNode?.isBoss || false,
                        scaling: realNode?.scaling || null,
                        // Position near the source node
                        sourceNodeId: sourceId
                    });
                }

                // Create link to placeholder
                processedLinks.push({
                    ...link,
                    target: placeholderId,
                    originalTarget: targetId
                });
            } else if (!sourceDiscovered && targetDiscovered && !link.oneWay) {
                // Target discovered, source not (bidirectional): create placeholder for source
                const placeholderId = `???_${targetId}_${sourceId}`;
                placeholderMap.set(placeholderId, sourceId);

                if (!placeholderNodes.find(n => n.id === placeholderId)) {
                    const realNode = nodeMap.get(sourceId);
                    placeholderNodes.push({
                        id: placeholderId,
                        realId: sourceId,
                        isPlaceholder: true,
                        isBoss: realNode?.isBoss || false,
                        scaling: realNode?.scaling || null,
                        sourceNodeId: targetId
                    });
                }

                processedLinks.push({
                    ...link,
                    source: placeholderId,
                    originalSource: sourceId
                });
            }
            // If neither is discovered, don't show the link
        });

        visibleNodes = [...discoveredNodes, ...placeholderNodes];
        visibleLinks = processedLinks;

        // Mark discovered nodes with their status
        visibleNodes.forEach(d => {
            if (!d.isPlaceholder) {
                d.explorationStatus = { visible: true, discovered: true, accessible: true };
            } else {
                d.explorationStatus = { visible: true, discovered: false, accessible: true };
            }
        });
    } else {
        visibleNodes = nodes;
        visibleLinks = links;
    }

    const visibleNodeIds = new Set(visibleNodes.map(d => d.id));
    
    // Stop previous simulation
    const oldSimulation = State.getSimulation();
    if (oldSimulation) oldSimulation.stop();
    
    // Restore node positions if preserving layout
    if (preservePositions) {
        restoreNodePositions(visibleNodes, visibleLinks);
    }
    
    // Create force simulation
    const simulation = d3.forceSimulation(visibleNodes)
        .force("link", d3.forceLink(visibleLinks)
            .id(d => d.id)
            .distance(100)
            .strength(0.5))
        .force("charge", d3.forceManyBody()
            .strength(-300)
            .distanceMax(500))
        .force("center", preservePositions ? null : d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(30))
        .force("x", preservePositions ? null : d3.forceX(width / 2).strength(0.03))
        .force("y", preservePositions ? null : d3.forceY(height / 2).strength(0.03));
    
    State.setSimulation(simulation);
    
    // Unfreeze nodes after layout stabilizes
    if (preservePositions) {
        unfreezeNodesAfterDelay(simulation);
    }
    
    // Draw links (path 'd' attribute will be set by tick handler)
    const link = container.append("g")
        .attr("class", "links")
        .selectAll("path")
        .data(visibleLinks)
        .join("path")
        .attr("class", d => {
            let cls = `link ${d.type}`;
            if (d.requiredItemFrom) cls += ' requires-item';
            return cls;
        });
    
    // Draw nodes
    const node = container.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(visibleNodes)
        .join("g")
        .attr("class", d => getNodeClass(d, explorationMode))
        .call(d3.drag()
            .on("start", (event) => dragstarted(event, simulation))
            .on("drag", dragged)
            .on("end", (event) => dragended(event, simulation)));
    
    node.append("circle")
        .attr("r", d => {
            if (explorationMode && !d.explorationStatus.discovered) return 7;
            return d.isBoss ? 10 : 7;
        });
    
    node.append("text")
        .attr("dx", 12)
        .attr("dy", 4)
        .text(d => getNodeLabel(d, explorationMode, explorationState));

    // Setup interactions
    setupTooltip(node, nodeConnections, explorationMode, explorationState, placeholderMap, nodeMap, visibleLinks);
    setupNodeClick(node, svg, nodeConnections, explorationMode, explorationState, placeholderMap, visibleLinks);
    setupSearch(node, link, nodes);
    
    // Simulation tick handler
    simulation.on("tick", () => {
        link.attr("d", d => {
            const sx = d.source.x ?? 0, sy = d.source.y ?? 0;
            const tx = d.target.x ?? 0, ty = d.target.y ?? 0;
            const dx = tx - sx;
            const dy = ty - sy;
            const dr = Math.sqrt(dx * dx + dy * dy) * 2;
            return `M${sx},${sy}A${dr},${dr} 0 0,1 ${tx},${ty}`;
        });
        
        node.attr("transform", d => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });
    
    // Initial zoom to fit (only on first render)
    if (!preservePositions) {
        setTimeout(() => {
            const bounds = container.node()?.getBBox();
            if (!bounds || bounds.width === 0 || bounds.height === 0) return;
            
            const fullWidth = bounds.width;
            const fullHeight = bounds.height;
            const midX = bounds.x + fullWidth / 2;
            const midY = bounds.y + fullHeight / 2;
            
            const scale = 0.8 / Math.max(fullWidth / width, fullHeight / height);
            if (!isFinite(scale) || scale <= 0) return;
            
            const translate = [width / 2 - scale * midX, height / 2 - scale * midY];
            if (!isFinite(translate[0]) || !isFinite(translate[1])) return;
            
            svg.transition()
                .duration(750)
                .call(zoom.transform, d3.zoomIdentity
                    .translate(translate[0], translate[1])
                    .scale(scale));
        }, 2000);
    }
    
    // Re-apply frontier highlight if active AND no node is selected
    // (if a node is selected, applySelectionHighlights already handled it)
    if (State.isFrontierHighlightActive() && !State.getSelectedNodeId()) {
        setTimeout(() => State.emit('frontierHighlightChanged', true), 100);
    }

    // Update tag stats display
    updateTagStats();

    // Re-apply tag highlight if filters are active
    if (selectedTagFilters.size > 0) {
        setTimeout(() => applyTagHighlight(), 100);
    }

    // Sync state after render completes (to capture restored highlights)
    if (preservePositions) {
        setTimeout(() => State.emit('graphRenderCompleted'), 150);
    }
}

// ============================================================
// HELPER FUNCTIONS
// ============================================================

function updateButtonVisibility(explorationMode) {
    const resetBtn = document.getElementById('reset-exploration-btn');
    const frontierCheckbox = document.getElementById('show-frontier-checkbox');
    const frontierLabel = frontierCheckbox?.closest('label');

    if (resetBtn) resetBtn.classList.toggle('hidden', !explorationMode);
    if (frontierLabel) {
        frontierLabel.classList.toggle('hidden', !explorationMode);
    }
    if (frontierCheckbox) {
        frontierCheckbox.checked = false;
    }
}

// ============================================================
// TAG STATS & FILTERING
// ============================================================

function updateTagStats() {
    const explorationMode = State.isExplorationMode();
    const explorationState = State.getExplorationState();
    const statsTagsContainer = document.getElementById('stats-tags');
    const statsTagsList = document.getElementById('stats-tags-list');

    if (!statsTagsContainer || !statsTagsList) return;

    // Hide tag stats if not in exploration mode or no tags
    if (!explorationMode || !explorationState || !explorationState.tags) {
        statsTagsContainer.classList.add('hidden');
        return;
    }

    // Count occurrences of each tag
    const tagCounts = new Map();
    explorationState.tags.forEach((tags) => {
        tags.forEach(tagId => {
            tagCounts.set(tagId, (tagCounts.get(tagId) || 0) + 1);
        });
    });

    // Hide if no tags are used
    if (tagCounts.size === 0) {
        statsTagsContainer.classList.add('hidden');
        return;
    }

    // Show and populate
    statsTagsContainer.classList.remove('hidden');
    statsTagsList.innerHTML = '';

    State.AVAILABLE_TAGS.forEach(tag => {
        const count = tagCounts.get(tag.id) || 0;
        if (count === 0) return;

        const tagEl = document.createElement('div');
        tagEl.className = 'stats-tag' + (selectedTagFilters.has(tag.id) ? ' active' : '');
        tagEl.setAttribute('data-tag-id', tag.id);
        tagEl.innerHTML = `<span class="tag-emoji">${tag.emoji}</span><span class="tag-count">${count}</span>`;
        tagEl.title = `Click to highlight areas with this tag`;

        tagEl.addEventListener('click', () => {
            toggleTagFilter(tag.id);
        });

        statsTagsList.appendChild(tagEl);
    });
}

function toggleTagFilter(tagId) {
    if (selectedTagFilters.has(tagId)) {
        selectedTagFilters.delete(tagId);
    } else {
        selectedTagFilters.add(tagId);
    }

    // Update UI
    document.querySelectorAll('.stats-tag').forEach(el => {
        const id = el.getAttribute('data-tag-id');
        el.classList.toggle('active', selectedTagFilters.has(id));
    });

    // Apply highlight
    applyTagHighlight();
}

function applyTagHighlight() {
    const svg = d3.select("#graph-container svg");
    const nodes = svg.selectAll(".node");
    const links = svg.selectAll(".link");
    const explorationState = State.getExplorationState();

    if (selectedTagFilters.size === 0) {
        // Clear tag highlight
        nodes.classed("tag-highlighted", false).classed("dimmed", false);
        links.classed("dimmed", false);

        // Restore frontier highlight if active
        if (State.isFrontierHighlightActive()) {
            State.emit('frontierHighlightChanged', true);
        }
        // Restore selection highlight if a node is selected
        State.emit('restoreSelectionHighlight');

        State.emit('tagFilterChanged');
        return;
    }

    // Find nodes with any of the selected tags
    const matchingNodeIds = new Set();
    if (explorationState && explorationState.tags) {
        explorationState.tags.forEach((tags, nodeId) => {
            if (tags.some(tagId => selectedTagFilters.has(tagId))) {
                matchingNodeIds.add(nodeId);
            }
        });
    }

    // Apply highlight
    nodes.classed("tag-highlighted", d => matchingNodeIds.has(d.id))
         .classed("dimmed", d => !matchingNodeIds.has(d.id));

    links.classed("dimmed", true);

    State.emit('tagFilterChanged');
}

export function clearTagFilters() {
    selectedTagFilters.clear();
    document.querySelectorAll('.stats-tag').forEach(el => {
        el.classList.remove('active');
    });
    applyTagHighlight();
}

function getNodeClass(d, explorationMode) {
    let cls = "node";

    // Placeholder nodes (???)
    if (d.isPlaceholder) {
        cls += " undiscovered accessible";
        return cls;
    }

    if (explorationMode && !d.explorationStatus.discovered) {
        cls += " undiscovered";
        if (d.explorationStatus.accessible) cls += " accessible";
    } else {
        if (d.id === State.START_NODE) cls += " start";
        else if (d.id === "Stone Platform") cls += " end";
        else if (d.isBoss) cls += " boss";
        else cls += " normal";
        if (d.isHub) cls += " hub";
    }

    return cls;
}

function getNodeLabel(d, explorationMode, explorationState) {
    // Placeholder nodes always show "???"
    if (d.isPlaceholder) {
        return "???";
    }

    if (explorationMode && !d.explorationStatus.discovered) {
        return "???";
    }

    let label = d.id;
    if (explorationMode && explorationState && explorationState.tags) {
        const tags = explorationState.tags.get(d.id);
        if (tags && tags.length > 0) {
            const emojis = tags.map(tagId => {
                const tag = State.AVAILABLE_TAGS.find(t => t.id === tagId);
                return tag ? tag.emoji : '';
            }).filter(e => e).join('');
            label += ' ' + emojis;
        }
    }

    return label;
}

function restoreNodePositions(nodes, links) {
    const nodePositions = State.getNodePositions();

    // First pass: restore known positions for non-placeholder nodes
    nodes.forEach(node => {
        if (node.isPlaceholder) return; // Handle placeholders separately

        const savedPos = nodePositions.get(node.id);
        if (savedPos && typeof savedPos.x === 'number' && typeof savedPos.y === 'number' &&
            !isNaN(savedPos.x) && !isNaN(savedPos.y) && isFinite(savedPos.x) && isFinite(savedPos.y)) {
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
        if (sourceNode && typeof sourceNode.x === 'number' && typeof sourceNode.y === 'number' &&
            !isNaN(sourceNode.x) && !isNaN(sourceNode.y)) {
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
            const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
            const targetId = typeof l.target === 'object' ? l.target.id : l.target;
            return sourceId === node.id || targetId === node.id;
        });

        if (connectedLink) {
            const sourceId = typeof connectedLink.source === 'object' ? connectedLink.source.id : connectedLink.source;
            const targetId = typeof connectedLink.target === 'object' ? connectedLink.target.id : connectedLink.target;
            const neighborId = sourceId === node.id ? targetId : sourceId;
            const neighborNode = nodes.find(n => n.id === neighborId);

            if (neighborNode && typeof neighborNode.x === 'number' && typeof neighborNode.y === 'number' &&
                !isNaN(neighborNode.x) && !isNaN(neighborNode.y)) {
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

// Simple hash function for deterministic positioning
function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash);
}

function unfreezeNodesAfterDelay(simulation) {
    setTimeout(() => {
        const nodePositions = State.getNodePositions();
        simulation.nodes().forEach(node => {
            if (nodePositions.has(node.id)) {
                node.fx = null;
                node.fy = null;
            }
        });
        simulation.alpha(0.1).restart();
    }, 500);
}

// ============================================================
// DRAG HANDLERS
// ============================================================

function dragstarted(event, simulation) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
}

function dragged(event) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
}

function dragended(event, simulation) {
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
    
    State.saveAllNodePositions();
    State.emit('nodePositionsSaved');
}

// ============================================================
// TOOLTIP
// ============================================================

// Track tooltip subscription for cleanup between renders
let tooltipSubscriptionCleanup = null;

function setupTooltip(node, nodeConnections, explorationMode, explorationState, placeholderMap, nodeMap, visibleLinks) {
    // Cleanup previous subscription to avoid duplicates
    if (tooltipSubscriptionCleanup) {
        tooltipSubscriptionCleanup();
        tooltipSubscriptionCleanup = null;
    }

    const tooltip = d3.select("#tooltip");
    // Check if tooltip was already pinned (survives re-render)
    let tooltipPinned = tooltip.classed("pinned");
    let isDraggingTooltip = false;
    let tooltipDragOffset = { x: 0, y: 0 };

    // Tooltip drag
    tooltip.on("mousedown", function(event) {
        if (event.target.tagName === 'H3' && tooltipPinned) {
            isDraggingTooltip = true;
            const rect = this.getBoundingClientRect();
            tooltipDragOffset.x = event.clientX - rect.left;
            tooltipDragOffset.y = event.clientY - rect.top;
            event.preventDefault();
        }
    });

    d3.select(document).on("mousemove.tooltip", function(event) {
        if (isDraggingTooltip) {
            tooltip.style("left", (event.clientX - tooltipDragOffset.x) + "px")
                   .style("top", (event.clientY - tooltipDragOffset.y) + "px");
        }
    });

    d3.select(document).on("mouseup.tooltip", function() {
        isDraggingTooltip = false;
    });

    // Track current tooltip node for refresh
    let currentTooltipNode = null;
    let currentTooltipPosition = null;

    function refreshTooltip() {
        if (currentTooltipNode && currentTooltipPosition) {
            // Refresh with updated exploration state
            const content = buildTooltipContent(currentTooltipNode, nodeConnections, explorationMode, State.getExplorationState(), true, placeholderMap, nodeMap, visibleLinks);
            tooltip.html(`<span class="close-btn">&times;</span>${content}`);
            setupTooltipHandlers();
        }
    }
    
    function setupTooltipHandlers() {
        tooltip.select(".close-btn").on("click", () => {
            hideTooltip();
            State.emit('tooltipClosed');
        });

        // Discover/undiscover buttons
        tooltip.select(".discover-btn").on("click", function() {
            const nodeId = this.getAttribute("data-node-id");
            const sourceNodeId = this.getAttribute("data-source-node-id");
            const isOneWay = this.getAttribute("data-one-way") === 'true';

            if (nodeId) {
                // If discovering from a placeholder, set the real node as selected
                // so after re-render it stays selected
                State.setSelectedNodeId(nodeId);

                // Pass the source node and link info for proper link discovery tracking
                const viaLink = sourceNodeId ? { oneWay: isOneWay } : null;
                Exploration.discoverArea(nodeId, sourceNodeId || null, viaLink);
                // The graph will re-render; tooltip will be refreshed via graphNeedsRender
            }
        });

        tooltip.select(".undiscover-btn").on("click", function() {
            const nodeId = this.getAttribute("data-node-id");
            if (nodeId) {
                hideTooltip();
                // Store the nodeId to select placeholder after re-render (if unique)
                State.setPendingUndiscoveredNodeId(nodeId);
                Exploration.undiscoverArea(nodeId);
            }
        });
        
        // Tag toggles
        tooltip.selectAll(".node-tag.clickable").on("click", function() {
            const tagId = this.getAttribute("data-tag-id");
            const nodeId = this.getAttribute("data-node-id");
            if (tagId && nodeId) {
                Exploration.toggleTag(nodeId, tagId);
                d3.select(this).classed("inactive", !d3.select(this).classed("inactive"));
            }
        });
    }
    
    function showTooltip(event, d, pinned = false) {
        currentTooltipNode = d;
        currentTooltipPosition = { x: event.pageX, y: event.pageY };

        const content = buildTooltipContent(d, nodeConnections, explorationMode, explorationState, pinned, placeholderMap, nodeMap, visibleLinks);
        tooltip.html(`<span class="close-btn">&times;</span>${content}`)
            .style("left", (event.pageX + 15) + "px")
            .style("top", Math.min(event.pageY - 10, window.innerHeight - 400) + "px")
            .classed("visible", true)
            .classed("pinned", pinned);

        setupTooltipHandlers();
    }
    
    function hideTooltip() {
        tooltip.classed("visible", false).classed("pinned", false);
        tooltipPinned = false;
        currentTooltipNode = null;
        currentTooltipPosition = null;
        State.setSelectedNodeId(null);
    }

    // Restore tooltip state if it was pinned before re-render
    if (tooltipPinned) {
        const selectedNodeId = State.getSelectedNodeId();
        if (selectedNodeId) {
            const selectedNodeData = node.data().find(n => n.id === selectedNodeId);
            if (selectedNodeData) {
                currentTooltipNode = selectedNodeData;
                // Rebuild tooltip content with the new node data
                const content = buildTooltipContent(selectedNodeData, nodeConnections, explorationMode, State.getExplorationState(), true, placeholderMap, nodeMap, visibleLinks);
                tooltip.html(`<span class="close-btn">&times;</span>${content}`);
                setupTooltipHandlers();
            } else {
                // Node no longer exists (e.g., placeholder was replaced), hide tooltip
                hideTooltip();
            }
        }
    }

    node.on("mouseenter", (event, d) => {
        if (!tooltipPinned) showTooltip(event, d, false);
    })
    .on("mousemove", (event) => {
        if (!tooltipPinned) {
            tooltip.style("left", (event.pageX + 15) + "px")
                .style("top", Math.min(event.pageY - 10, window.innerHeight - 400) + "px");
        }
    })
    .on("mouseleave", () => {
        if (!tooltipPinned) tooltip.classed("visible", false);
    });
    
    // Expose for click handler
    node.showTooltipPinned = (event, d) => {
        tooltipPinned = true;
        // If no event provided, use node position
        if (!event && d.x !== undefined && d.y !== undefined) {
            const transform = State.getCurrentZoomTransform() || d3.zoomIdentity;
            const screenX = transform.applyX(d.x);
            const screenY = transform.applyY(d.y);
            event = { pageX: screenX + 50, pageY: screenY };
        }
        showTooltip(event, d, true);
    };

    node.hideTooltip = hideTooltip;
    node.isTooltipPinned = () => tooltipPinned;

    // Listen for programmatic tooltip requests (e.g., after discovery from mod)
    tooltipSubscriptionCleanup = State.subscribe('showTooltipForNode', ({ nodeId }) => {
        const targetNodeData = node.data().find(n => n.id === nodeId);
        if (targetNodeData) {
            node.showTooltipPinned(null, targetNodeData);
        }
    });
}

function buildTooltipContent(d, nodeConnections, explorationMode, explorationState, pinned, placeholderMap, nodeMap, visibleLinks) {
    // Handle placeholder nodes
    if (d.isPlaceholder) {
        const realId = d.realId;

        let html = `<h3>??? (Unknown Area)</h3>`;
        html += `<p class="scaling" style="font-style: italic; color: #6a5a4a;">Discover this area to reveal its details</p>`;

        // Show how to reach this area (the link from the source node)
        html += '<div class="connections">';
        html += '<div class="conn-title">How to reach</div>';

        // Find the link connecting to this placeholder
        const relevantLink = visibleLinks?.find(l => {
            const targetId = typeof l.target === 'object' ? l.target.id : l.target;
            const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
            return targetId === d.id || sourceId === d.id;
        });

        if (relevantLink) {
            const linkSourceId = typeof relevantLink.source === 'object' ? relevantLink.source.id : relevantLink.source;
            const linkTargetId = typeof relevantLink.target === 'object' ? relevantLink.target.id : relevantLink.target;

            // Determine if we're using the link in reverse direction
            // The placeholder's sourceNodeId tells us where we came from
            const isReversed = d.sourceNodeId === linkTargetId;

            // The "from" node is the discovered node we're coming from
            const fromNodeId = d.sourceNodeId;

            // Details depend on direction:
            // - Normal direction: fromDetails = sourceDetails, toDetails = targetDetails
            // - Reversed direction: fromDetails = targetDetails, toDetails = sourceDetails
            const fromDetails = isReversed ? (relevantLink.targetDetails || '') : (relevantLink.sourceDetails || '');
            const toDetails = isReversed ? (relevantLink.sourceDetails || '') : (relevantLink.targetDetails || '');

            html += `<div class="conn-item ${relevantLink.type}${relevantLink.requiredItemFrom ? ' has-requirement' : ''}">`;
            html += `← ${fromNodeId}`;
            // Show where we depart FROM (not where we arrive - that would be a spoiler)
            if (fromDetails) {
                html += `<div class="conn-details expanded">From: ${fromDetails}</div>`;
            }

            // Required item info - extract from description or show zones
            const requiredItem = extractRequiredItemFromDescription(fromDetails, toDetails);
            if (requiredItem) {
                html += `<div class="requires-info">🔑 Requires: ${requiredItem}`;
                if (relevantLink.requiredItemFrom) {
                    const zones = parseRequiredItemZones(relevantLink.requiredItemFrom);
                    html += `<span class="zones-hint" title="${zones.join(', ')}"> (hover for locations)</span>`;
                }
                html += `</div>`;
            } else if (relevantLink.requiredItemFrom) {
                const zones = parseRequiredItemZones(relevantLink.requiredItemFrom);
                html += `<div class="requires-info">🔑 Requires item <span class="zones-hint" title="${zones.join(', ')}">(hover for locations)</span></div>`;
            }

            html += '</div>';
        }

        html += '</div>';

        // Action button (not shown for viewers)
        if (pinned && !State.isViewerMode()) {
            // Include source node info for link discovery tracking
            const sourceNodeId = d.sourceNodeId || '';
            const isOneWay = relevantLink?.oneWay ? 'true' : 'false';
            html += `<button class="discover-btn" data-node-id="${realId}" data-source-node-id="${sourceNodeId}" data-one-way="${isOneWay}">Mark as discovered</button>`;
        }

        return html;
    }

    // Regular node handling
    const conns = nodeConnections.get(d.id);
    const isUndiscovered = explorationMode && explorationState && !explorationState.discovered.has(d.id);

    let html = '';

    if (isUndiscovered) {
        html = `<h3>??? (Unknown Area)</h3>`;
        html += `<p class="scaling" style="font-style: italic; color: #6a5a4a;">Discover this area to reveal its details</p>`;
    } else {
        html = `<h3>${d.id}${d.isBoss ? '<span class="boss-badge">Boss</span>' : ''}</h3>`;

        if (d.scaling) {
            html += `<p class="scaling">Scaling: ${d.scaling}</p>`;
        }

        // Tags
        if (explorationMode && explorationState) {
            const activeTags = explorationState.tags.get(d.id) || [];

            if (pinned) {
                html += '<div class="node-tags">';
                State.AVAILABLE_TAGS.forEach(tag => {
                    const isActive = activeTags.includes(tag.id);
                    html += `<span class="node-tag clickable${isActive ? '' : ' inactive'}" data-tag-id="${tag.id}" data-node-id="${d.id}">${tag.emoji}</span>`;
                });
                html += '</div>';
            } else if (activeTags.length > 0) {
                html += '<div class="node-tags">';
                activeTags.forEach(tagId => {
                    const tag = State.AVAILABLE_TAGS.find(t => t.id === tagId);
                    if (tag) html += `<span class="node-tag">${tag.emoji}</span>`;
                });
                html += '</div>';
            }
        }

    }

    // Connections
    if (conns && (conns.incoming.length > 0 || conns.outgoing.length > 0)) {
        html += '<div class="connections">';

        const incomingToShow = isUndiscovered
            ? conns.incoming.filter(({ link, reversed }) => {
                // Determine actual source based on whether link is reversed
                const linkSource = typeof link.source === 'object' ? link.source.id : link.source;
                const linkTarget = typeof link.target === 'object' ? link.target.id : link.target;
                const actualSource = reversed ? linkTarget : linkSource;
                return explorationState && explorationState.discovered.has(actualSource);
            })
            : conns.incoming;

        if (incomingToShow.length > 0) {
            html += `<div class="conn-title">${isUndiscovered ? 'How to reach' : 'Entrances'}</div>`;
            html += buildConnectionsList(incomingToShow, 'incoming', isUndiscovered, explorationMode, explorationState, pinned, d.id);
        }

        if (!isUndiscovered && conns.outgoing.length > 0) {
            html += '<div class="conn-title" style="margin-top: 8px;">Exits</div>';
            html += buildConnectionsList(conns.outgoing, 'outgoing', false, explorationMode, explorationState, pinned, d.id);
        }

        html += '</div>';
    }

    // Action buttons (not shown for viewers)
    if (isUndiscovered && pinned && !State.isViewerMode()) {
        html += `<button class="discover-btn" data-node-id="${d.id}">Mark as discovered</button>`;
    }

    if (explorationMode && !isUndiscovered && pinned && d.id !== State.START_NODE && !State.isViewerMode()) {
        html += `<button class="undiscover-btn" data-node-id="${d.id}">↩️ Mark as undiscovered</button>`;
    }

    return html;
}

function buildConnectionsList(connections, direction, isUndiscovered, explorationMode, explorationState, pinned, currentNodeId) {
    let html = '';
    const maxShow = pinned ? connections.length : 5;

    connections.slice(0, maxShow).forEach(({ link, reversed }) => {
        const linkSource = typeof link.source === 'object' ? link.source.id : link.source;
        const linkTarget = typeof link.target === 'object' ? link.target.id : link.target;

        // Determine actual source/target based on whether link is reversed
        // For a normal link: source -> target
        // For a reversed link (bidirectional): target -> source
        const actualSource = reversed ? linkTarget : linkSource;
        const actualTarget = reversed ? linkSource : linkTarget;

        // The neighbor is the node we're connecting to (not the current node)
        const neighborName = direction === 'incoming' ? actualSource : actualTarget;

        // Details also need to be swapped for reversed links
        const fromDetails = reversed ? (link.targetDetails || '') : (link.sourceDetails || '');
        const toDetails = reversed ? (link.sourceDetails || '') : (link.targetDetails || '');

        const hasReq = link.requiredItemFrom;

        // Check if THIS SPECIFIC link is discovered (not just any link between endpoints)
        // This prevents parallel links (e.g., preexisting + random) from all showing as
        // discovered when only one was traversed
        const isLinkDiscovered = !explorationMode || !explorationState ||
            (link.id && explorationState.discoveredLinks.has(link.id));

        // For outgoing: hide if target not discovered OR link not discovered
        // For incoming: hide if source not discovered OR link not discovered
        let displayName = neighborName;
        if (explorationMode && explorationState) {
            if (direction === 'outgoing' && (!explorationState.discovered.has(actualTarget) || !isLinkDiscovered)) {
                displayName = '???';
            } else if (direction === 'incoming' && (!explorationState.discovered.has(actualSource) || !isLinkDiscovered)) {
                displayName = '???';
            }
        }

        html += `<div class="conn-item ${link.type}${hasReq ? ' has-requirement' : ''}">`;
        html += direction === 'incoming' ? `← ${displayName}` : `→ ${displayName}`;

        // Details: show arrival details (toDetails) for incoming, departure details (fromDetails) for outgoing
        // But hide source info for undiscovered incoming links (no spoilers)
        if (isUndiscovered && direction === 'incoming') {
            // Placeholder node: show where it arrives
            if (toDetails) html += `<div class="conn-details">To: ${toDetails}</div>`;
        } else if (displayName === '???') {
            // Unknown connection: show only the "safe" side details
            if (direction === 'incoming' && toDetails) {
                html += `<div class="conn-details">To: ${toDetails}</div>`;
            } else if (direction === 'outgoing' && fromDetails) {
                html += `<div class="conn-details">From: ${fromDetails}</div>`;
            }
        } else if (fromDetails || toDetails) {
            html += `<div class="conn-details">`;
            if (fromDetails) html += `From: ${fromDetails}`;
            if (fromDetails && toDetails) html += `<br>`;
            if (toDetails) html += `To: ${toDetails}`;
            html += `</div>`;
        }

        // Required item info - extract from description or show zones on hover
        const requiredItem = extractRequiredItemFromDescription(fromDetails, toDetails);
        if (requiredItem) {
            html += `<div class="requires-info">🔑 Requires: ${requiredItem}`;
            if (hasReq) {
                const zones = parseRequiredItemZones(link.requiredItemFrom);
                html += `<span class="zones-hint" title="${zones.join(', ')}"> (hover for locations)</span>`;
            }
            html += `</div>`;
        } else if (hasReq) {
            const zones = parseRequiredItemZones(link.requiredItemFrom);
            html += `<div class="requires-info">🔑 Requires item <span class="zones-hint" title="${zones.join(', ')}">(hover for locations)</span></div>`;
        }

        html += `</div>`;
    });

    if (!pinned && connections.length > 5) {
        html += `<div class="conn-item" style="color: #6a5d45;">... click to see ${connections.length - 5} more</div>`;
    }

    return html;
}

// ============================================================
// NODE CLICK
// ============================================================

function setupNodeClick(node, svg, nodeConnections, explorationMode, explorationState, placeholderMap, visibleLinks) {
    // Restore selected node from state if exists
    let selectedNode = State.getSelectedNodeId();

    // Clear selection helper
    function clearSelection() {
        node.hideTooltip();
        selectedNode = null;

        // If frontier mode is active, re-apply frontier view
        // Otherwise just reset highlights
        if (State.isFrontierHighlightActive()) {
            State.emit('restoreFrontierHighlight');
        } else {
            resetHighlight(node, svg);
        }
    }

    // Listen for tooltip close button
    State.subscribe('tooltipClosed', () => {
        selectedNode = null;
        if (State.isFrontierHighlightActive()) {
            State.emit('restoreFrontierHighlight');
        } else {
            resetHighlight(node, svg);
        }
    });

    // Check if we need to select a placeholder after undiscover
    const pendingUndiscoveredNodeId = State.getPendingUndiscoveredNodeId();
    if (pendingUndiscoveredNodeId) {
        State.clearPendingUndiscoveredNodeId();

        // Find placeholders for the undiscovered node
        const placeholders = [];
        node.each(function(d) {
            if (d.isPlaceholder && d.realId === pendingUndiscoveredNodeId) {
                placeholders.push(d);
            }
        });

        // Only select if there's exactly one placeholder
        if (placeholders.length === 1) {
            const placeholder = placeholders[0];
            selectedNode = placeholder.id;
            State.setSelectedNodeId(placeholder.id);
            node.showTooltipPinned(null, placeholder);
            applySelectionHighlights(placeholder.id, placeholder);
        }
    }

    // Helper function to apply selection highlights
    function applySelectionHighlights(nodeId, nodeData) {
        let connectedNodes = new Set();

        // Special handling for placeholder nodes
        if (nodeData?.isPlaceholder) {
            // Highlight the placeholder itself
            connectedNodes.add(nodeId);
            // Highlight the source node (discovered node it's connected to)
            if (nodeData.sourceNodeId) {
                connectedNodes.add(nodeData.sourceNodeId);

                // If "Path to start" is enabled, also show path from start to source node
                const showPathFromStart = document.getElementById('show-path-from-start')?.checked;
                if (showPathFromStart) {
                    const pathResult = Exploration.findPathFromStart(nodeData.sourceNodeId);
                    pathResult.nodes.forEach(n => connectedNodes.add(n));
                }
            }
        } else {
            // Normal node handling
            const showPathFromStart = document.getElementById('show-path-from-start')?.checked;

            if (showPathFromStart) {
                // Path from start mode: show path + direct neighbors only (no linear propagation)
                const pathResult = Exploration.findPathFromStart(nodeId);
                pathResult.nodes.forEach(n => connectedNodes.add(n));

                // Add direct neighbors of selected node
                connectedNodes.add(nodeId);
                visibleLinks.forEach(link => {
                    const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
                    const targetId = typeof link.target === 'object' ? link.target.id : link.target;
                    if (sourceId === nodeId) connectedNodes.add(targetId);
                    if (targetId === nodeId) connectedNodes.add(sourceId);
                });
            } else {
                // Normal mode: follow linear path (subway line behavior)
                const localResult = Exploration.followLinearPath(nodeId);
                connectedNodes = localResult.nodes;
            }

            // Also include placeholder nodes connected to any node in connectedNodes
            node.each(function(n) {
                if (n.isPlaceholder && n.sourceNodeId && connectedNodes.has(n.sourceNodeId)) {
                    connectedNodes.add(n.id);
                }
            });
        }

        // Highlight nodes
        node.classed("highlighted", n => connectedNodes.has(n.id))
            .classed("dimmed", n => !connectedNodes.has(n.id));

        // Highlight links: a link is highlighted if both its endpoints are in connectedNodes
        svg.selectAll(".link")
            .classed("highlighted", l => {
                const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
                const targetId = typeof l.target === 'object' ? l.target.id : l.target;
                return connectedNodes.has(sourceId) && connectedNodes.has(targetId);
            })
            .classed("dimmed", l => {
                const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
                const targetId = typeof l.target === 'object' ? l.target.id : l.target;
                return !(connectedNodes.has(sourceId) && connectedNodes.has(targetId));
            });
    }

    // If a node was selected, restore its highlight after a short delay
    // to ensure DOM is fully updated
    if (selectedNode) {
        const selectedNodeData = node.data().find(n => n.id === selectedNode);
        if (selectedNodeData) {
            // Apply immediately and also after a delay to ensure it sticks
            applySelectionHighlights(selectedNode, selectedNodeData);
            setTimeout(() => applySelectionHighlights(selectedNode, selectedNodeData), 50);
        }
    }

    node.on("click", (event, d) => {
        event.stopPropagation();

        if (selectedNode === d.id && node.isTooltipPinned()) {
            clearSelection();
            return;
        }

        selectedNode = d.id;
        node.showTooltipPinned(event, d);

        // Always use applySelectionHighlights - it takes over from frontier mode
        applySelectionHighlights(d.id, d);
        State.setSelectedNodeId(d.id);

        State.emit('nodeSelected', { nodeId: d.id });
    });

    svg.on("click", () => clearSelection());

    // Listen for restore selection highlight event (e.g., after clearing frontier)
    State.subscribe('restoreSelectionHighlight', () => {
        if (selectedNode) {
            const selectedNodeData = node.data().find(n => n.id === selectedNode);
            applySelectionHighlights(selectedNode, selectedNodeData);
        }
    });

    // Listen for path-from-start checkbox changes
    State.subscribe('pathFromStartChanged', () => {
        const currentSelected = State.getSelectedNodeId();
        if (currentSelected) {
            // Re-select current nodes from DOM (in case graph was re-rendered)
            const currentNodes = d3.selectAll(".node");
            const selectedNodeData = currentNodes.data().find(n => n.id === currentSelected);
            if (selectedNodeData) {
                // Re-apply highlights using current DOM elements
                let connectedNodes = new Set();

                if (selectedNodeData.isPlaceholder) {
                    connectedNodes.add(currentSelected);
                    if (selectedNodeData.sourceNodeId) {
                        connectedNodes.add(selectedNodeData.sourceNodeId);
                        const showPathFromStart = document.getElementById('show-path-from-start')?.checked;
                        if (showPathFromStart) {
                            const pathResult = Exploration.findPathFromStart(selectedNodeData.sourceNodeId);
                            pathResult.nodes.forEach(n => connectedNodes.add(n));
                        }
                    }
                } else {
                    const localResult = Exploration.followLinearPath(currentSelected);
                    connectedNodes = localResult.nodes;
                    const showPathFromStart = document.getElementById('show-path-from-start')?.checked;
                    if (showPathFromStart) {
                        const pathResult = Exploration.findPathFromStart(currentSelected);
                        pathResult.nodes.forEach(n => connectedNodes.add(n));
                    }
                    // Include connected placeholders
                    currentNodes.each(function(n) {
                        if (n.isPlaceholder && n.sourceNodeId && connectedNodes.has(n.sourceNodeId)) {
                            connectedNodes.add(n.id);
                        }
                    });
                }

                currentNodes.classed("highlighted", n => connectedNodes.has(n.id))
                    .classed("dimmed", n => !connectedNodes.has(n.id));

                d3.selectAll(".link")
                    .classed("highlighted", l => {
                        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
                        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
                        return connectedNodes.has(sourceId) && connectedNodes.has(targetId);
                    })
                    .classed("dimmed", l => {
                        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
                        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
                        return !(connectedNodes.has(sourceId) && connectedNodes.has(targetId));
                    });
            }
        }
    });
}

function resetHighlight(node, svg) {
    node.classed("highlighted", false).classed("dimmed", false);
    svg.selectAll(".link").classed("highlighted", false).classed("dimmed", false);
    
    if (State.isFrontierHighlightActive()) {
        State.emit('frontierHighlightChanged', true);
    }
}

// ============================================================
// SEARCH
// ============================================================

function setupSearch(node, link, allNodes) {
    State.subscribe('searchMatched', ({ matchingIds }) => {
        node.classed("highlighted", n => matchingIds.has(n.id))
            .classed("dimmed", n => !matchingIds.has(n.id));
        link.classed("dimmed", true).classed("highlighted", false);
    });
    
    State.subscribe('searchCleared', () => {
        node.classed("highlighted", false).classed("dimmed", false);
        link.classed("dimmed", false).classed("highlighted", false);
    });
}

// ============================================================
// CENTER ON NODE
// ============================================================

/**
 * Center the view on a specific node with smooth animation
 * @param {string} nodeId - The ID of the node to center on
 * @param {number} duration - Animation duration in ms (default 500)
 */
export function centerOnNode(nodeId, duration = 500) {
    const svg = d3.select("#graph-container svg");
    const container = svg.select("g");
    const nodes = container.selectAll(".node");

    // Find the node data
    let targetNode = null;
    nodes.each(function(d) {
        if (d.id === nodeId) {
            targetNode = d;
        }
    });

    // Validate node exists and has valid coordinates
    if (!targetNode || targetNode.x === undefined || targetNode.y === undefined) {
        return;
    }
    if (!isFinite(targetNode.x) || !isFinite(targetNode.y)) {
        console.warn('centerOnNode: invalid coordinates for node', nodeId, targetNode.x, targetNode.y);
        return;
    }

    const width = window.innerWidth;
    const height = window.innerHeight;

    // Get current zoom transform
    const currentTransform = State.getCurrentZoomTransform() || d3.zoomIdentity;
    const scale = currentTransform.k;

    // Calculate translation to center the node
    const targetX = width / 2 - targetNode.x * scale;
    const targetY = height / 2 - targetNode.y * scale;

    // Create zoom behavior reference
    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
            container.attr("transform", event.transform);
            State.setCurrentZoomTransform(event.transform);
            State.emit('viewportChanged', event.transform);
        });

    // Animate to center
    svg.transition()
        .duration(duration)
        .call(zoom.transform, d3.zoomIdentity.translate(targetX, targetY).scale(scale));
}

// ============================================================
// EVENT SUBSCRIPTIONS
// ============================================================

State.subscribe('nodeTagsUpdated', ({ nodeId, tags }) => {
    // Update node label in graph
    const svg = d3.select("#graph-container svg");
    const explorationState = State.getExplorationState();

    svg.selectAll(".node")
        .filter(d => d.id === nodeId)
        .select("text")
        .text(d => {
            let label = d.id;
            if (tags && tags.length > 0) {
                const emojis = tags.map(tagId => {
                    const tag = State.AVAILABLE_TAGS.find(t => t.id === tagId);
                    return tag ? tag.emoji : '';
                }).filter(e => e).join('');
                label += ' ' + emojis;
            }
            return label;
        });

    // Update tag stats in the stats panel
    updateTagStats();

    // Re-apply tag highlight if filters are active
    if (selectedTagFilters.size > 0) {
        applyTagHighlight();
    }
});
