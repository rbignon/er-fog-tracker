/**
 * Not Found page - Displayed when a game or user doesn't exist.
 * Route: /not-found?type=game|user&back=/optional/back/url
 */

import * as Auth from '../auth.js';

/**
 * Show the not-found page.
 */
export function show() {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('not-found-page').classList.remove('hidden');
    document.body.classList.remove('graph-mode');
}

/**
 * Initialize page (no persistent handlers needed).
 */
export function init() {
    // Nothing to initialize
}

/**
 * Validate and sanitize a back URL to prevent XSS.
 * Only allows same-origin URLs with safe protocols.
 * @param {string} url - The URL to validate
 * @returns {string|null} - Sanitized URL path or null if invalid
 */
function sanitizeBackUrl(url) {
    if (!url) return null;

    try {
        const parsed = new URL(url, window.location.origin);
        // Only allow same-origin URLs with safe protocols
        if (parsed.origin === window.location.origin && (parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
            return parsed.pathname + parsed.search;
        }
    } catch (e) {
        // Invalid URL, ignore it
    }
    return null;
}

/**
 * Route handler for not-found page.
 * Query params:
 * - type: 'game' | 'user' (determines message)
 * - back: URL to use for back button (optional)
 */
export function handleRoute({ query }) {
    show();

    const type = query.type || 'game';
    const backUrl = sanitizeBackUrl(query.back);

    const titleEl = document.getElementById('not-found-title');
    const messageEl = document.getElementById('not-found-message');
    const backLinkEl = document.getElementById('not-found-back-link');
    const actionEl = document.getElementById('not-found-action');

    // Set title and message based on type
    if (type === 'user') {
        titleEl.textContent = 'User not found';
        messageEl.textContent = "This user doesn't exist.";
    } else {
        titleEl.textContent = 'Game not found';
        messageEl.textContent = "This game doesn't exist or has been deleted.";
    }

    // Determine back link and action button
    let defaultBackUrl;
    let actionText;

    if (backUrl) {
        // Use provided back URL
        defaultBackUrl = backUrl;
        actionText = 'Go Back';
    } else if (type === 'user') {
        // No back URL, user not found -> go to players list
        defaultBackUrl = '/watch';
        actionText = 'Browse Players';
    } else if (Auth.isAuthenticated()) {
        // No back URL, game not found, logged in -> go to dashboard
        defaultBackUrl = '/dashboard';
        actionText = 'Go to Dashboard';
    } else {
        // No back URL, game not found, not logged in -> go to home
        defaultBackUrl = '/';
        actionText = 'Go Home';
    }

    backLinkEl.href = defaultBackUrl;
    actionEl.href = defaultBackUrl;
    actionEl.textContent = actionText;
}

export default {
    show,
    init,
    handleRoute,
};
