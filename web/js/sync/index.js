// ============================================================
// SYNC - WebSocket-based streamer sync (entry point)
// ============================================================

// Re-export public API
export { disconnect } from './common.js';
export { connectAsHost, initStreamUI, updateModConnectionIndicator, updateViewerCount } from './host.js';
export { connectAsViewer, restoreLastVisualState, updateHostConnectionIndicator } from './viewer.js';

// Register reconnection callbacks
import { registerReconnectFunctions } from './common.js';
import { connectAsHost } from './host.js';
import { connectAsViewer } from './viewer.js';

registerReconnectFunctions(connectAsHost, connectAsViewer);
