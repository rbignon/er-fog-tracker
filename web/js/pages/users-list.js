/**
 * Users list page - Public list of all players.
 * Route: /watch
 */

import * as Api from '../api.js';
import { escapeHtml } from '../sanitize.js';

/**
 * Show the users list page.
 */
export function show() {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('users-list-page').classList.remove('hidden');
    document.body.classList.remove('graph-mode');
}

/**
 * Initialize page (no persistent handlers needed).
 */
export function init() {
    // Nothing to initialize
}

/**
 * Load and render the users list.
 */
async function loadUsers() {
    const listEl = document.getElementById('users-list');
    const emptyEl = document.getElementById('users-empty');
    const loadingEl = document.getElementById('users-loading');
    const errorEl = document.getElementById('users-error');

    listEl.innerHTML = '';
    emptyEl.classList.add('hidden');
    errorEl.classList.add('hidden');
    loadingEl.classList.remove('hidden');

    try {
        const { users } = await Api.getUsers();

        loadingEl.classList.add('hidden');

        if (users.length === 0) {
            emptyEl.classList.remove('hidden');
            return;
        }

        users.forEach(user => {
            listEl.appendChild(createUserRow(user));
        });
    } catch (e) {
        loadingEl.classList.add('hidden');
        errorEl.textContent = e.detail || e.message || 'Failed to load players';
        errorEl.classList.remove('hidden');
    }
}

/**
 * Create a user row element.
 */
function createUserRow(user) {
    const row = document.createElement('a');
    row.className = 'user-row';
    row.href = `/watch/${encodeURIComponent(user.username)}`;

    // Add playing class if mod is connected
    if (user.modConnected) {
        row.classList.add('user-playing');
    }

    // Avatar with fallback
    const defaultAvatar = `data:image/svg+xml,${encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%237a6d55"><circle cx="12" cy="8" r="4"/><path d="M12 14c-6 0-8 3-8 6v1h16v-1c0-3-2-6-8-6z"/></svg>'
    )}`;

    // Build status badges
    let statusHtml = '';
    if (user.modConnected) {
        statusHtml += '<span class="status-badge status-playing" title="Playing now">Playing</span>';
    } else if (user.hostConnected) {
        statusHtml += '<span class="status-badge status-online" title="Online">Online</span>';
    } else if (user.lastSeenAt) {
        const relativeTime = formatRelativeTime(user.lastSeenAt);
        if (relativeTime) {
            const tooltip = escapeHtml(new Date(user.lastSeenAt).toLocaleString());
            statusHtml += `<span class="last-seen" title="${tooltip}">${escapeHtml(relativeTime)}</span>`;
        }
    }
    if (user.viewerCount > 0) {
        statusHtml += `<span class="viewer-count" title="${user.viewerCount} viewer${user.viewerCount > 1 ? 's' : ''}">👁 ${user.viewerCount}</span>`;
    }

    row.innerHTML = `
        <img class="user-avatar" src="" alt="${escapeHtml(user.displayName)}">
        <span class="user-name">${escapeHtml(user.displayName)}</span>
        <div class="user-status">${statusHtml}</div>
        <span class="user-arrow">→</span>
    `;

    // Set avatar src programmatically (CSP blocks inline onerror handlers)
    const avatarImg = row.querySelector('.user-avatar');
    avatarImg.src = user.avatarUrl || defaultAvatar;
    avatarImg.onerror = () => {
        avatarImg.src = defaultAvatar;
    };

    return row;
}

/**
 * Format a date as relative time (e.g., "2h ago", "3 days ago").
 * Returns null if date is invalid.
 */
function formatRelativeTime(dateString) {
    if (!dateString) return null;

    const date = new Date(dateString);
    if (isNaN(date.getTime())) return null;

    const now = new Date();
    const diffMs = now - date;

    // Handle future dates (clock skew)
    if (diffMs < 0) return 'just now';

    const diffMin = Math.floor(diffMs / 60000);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHour < 24) return `${diffHour}h ago`;
    if (diffDay < 30) return `${diffDay}d ago`;
    return date.toLocaleDateString();
}

/**
 * Route handler for users list page.
 */
export async function handleRoute() {
    show();
    await loadUsers();
}

export default {
    show,
    init,
    handleRoute,
};
