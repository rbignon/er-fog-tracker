/**
 * Application-wide constants.
 */

// =============================================================================
// Timing Constants (milliseconds)
// =============================================================================

export const TIMING = {
    // Graph rendering
    INITIAL_ZOOM_DELAY: 2000, // Delay before initial zoom-to-fit
    POST_RENDER_SETUP: 100, // Delay after render for highlight setup
    GRAPH_RENDER_COMPLETE: 150, // Delay before emitting graphRenderCompleted
    CENTER_ON_NODE: 300, // Animation duration for centering on a node
    NODE_UNFREEZE_DELAY: 500, // Delay before unfreezing nodes after layout

    // Sync throttling
    SYNC_THROTTLE: 50, // Throttle for state sync to viewers
    SYNC_THROTTLE_SLOW: 200, // Slower throttle for less critical syncs
    VIEWPORT_APPLY_DELAY: 200, // Delay before applying viewport changes

    // UI interactions
    SELECTION_RESTORE_DELAY: 50, // Delay before restoring selection highlights
    STREAM_UI_INIT: 50, // Delay for stream UI initialization
};

// =============================================================================
// WebSocket Constants
// =============================================================================

export const WS = {
    RECONNECT_DELAY_INITIAL: 1000, // Initial reconnect delay
    RECONNECT_DELAY_MAX: 30000, // Maximum reconnect delay
    RECONNECT_BACKOFF_FACTOR: 1.5, // Exponential backoff multiplier
    HEARTBEAT_INTERVAL: 15000, // Ping interval
    HEARTBEAT_TIMEOUT: 30000, // Time without pong before considering dead
};

// =============================================================================
// UI Constants
// =============================================================================

export const UI = {
    TOAST_DURATION: 5000, // Default toast notification duration
    MAX_SEARCH_RESULTS: 8, // Maximum search results to show
    DEBOUNCE_DELAY: 150, // Default debounce delay for inputs
};
