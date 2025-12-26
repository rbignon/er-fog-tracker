/**
 * Authentication module - Twitch OAuth token management.
 */

const TOKEN_KEY = 'fogtracker_api_token';
const USER_KEY = 'fogtracker_user';

let cachedUser = null;
let fetchingUser = null; // Promise to prevent concurrent fetches
let lastFetchError = null; // Track last fetch error to prevent redirect loops

/**
 * Check if user is authenticated.
 */
export function isAuthenticated() {
    return !!getToken();
}

/**
 * Get stored API token.
 */
export function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

/**
 * Get authorization headers for API requests.
 */
export function getAuthHeaders() {
    const token = getToken();
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
}

/**
 * Get cached user info.
 * Returns null if not authenticated or not yet fetched.
 */
export function getUser() {
    if (cachedUser) return cachedUser;

    const stored = localStorage.getItem(USER_KEY);
    if (stored) {
        try {
            cachedUser = JSON.parse(stored);
            return cachedUser;
        } catch {
            // Invalid JSON, clear it
            localStorage.removeItem(USER_KEY);
        }
    }
    return null;
}

/**
 * Fetch user info from server and cache it.
 * Returns null if not authenticated or fetch fails.
 * Prevents concurrent fetch requests.
 */
export async function fetchUser() {
    const token = getToken();
    if (!token) return null;

    // Return existing promise if already fetching
    if (fetchingUser) {
        return fetchingUser;
    }

    fetchingUser = (async () => {
        try {
            const response = await fetch('/auth/me', {
                headers: getAuthHeaders(),
            });

            if (!response.ok) {
                if (response.status === 401) {
                    // Token invalid, clear auth
                    clearAuth();
                    lastFetchError = 'auth';
                } else {
                    // Server error - track it to prevent redirect loops
                    lastFetchError = 'server';
                    console.error(`Server error: ${response.status}`);
                }
                return null;
            }

            // Clear any previous error on success
            lastFetchError = null;

            const user = await response.json();
            cachedUser = {
                id: user.id,
                username: user.twitch_username,
                displayName: user.twitch_display_name || user.twitch_username,
                avatarUrl: user.twitch_avatar_url,
                apiToken: user.api_token,
                modToken: user.mod_token,
            };

            localStorage.setItem(USER_KEY, JSON.stringify(cachedUser));
            return cachedUser;
        } catch (e) {
            console.error('Failed to fetch user:', e);
            lastFetchError = 'network';
            return null;
        } finally {
            fetchingUser = null;
        }
    })();

    return fetchingUser;
}

/**
 * Redirect to Twitch OAuth login.
 */
export function login() {
    window.location.href = '/auth/twitch';
}

/**
 * Clear authentication and redirect to landing.
 */
export function logout() {
    clearAuth();
    window.location.href = '/';
}

/**
 * Clear all auth data.
 */
function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    cachedUser = null;
    lastFetchError = null;
}

/**
 * Update cached user data (e.g., after regenerating mod token).
 * @param {Object} updates - Fields to update
 */
export function updateCachedUser(updates) {
    if (!cachedUser) return;
    Object.assign(cachedUser, updates);
    localStorage.setItem(USER_KEY, JSON.stringify(cachedUser));
}

/**
 * Get last fetch error type.
 * @returns {'auth' | 'server' | 'network' | null}
 */
export function getLastFetchError() {
    return lastFetchError;
}

/**
 * Clear the last fetch error.
 */
export function clearLastFetchError() {
    lastFetchError = null;
}

/**
 * Handle OAuth callback - extract token from URL and fetch user.
 * @param {string} token - The API token from callback URL
 * @returns {Promise<Object|null>} - User object or null on failure
 */
export async function handleCallback(token) {
    if (!token) return null;

    // Store token
    localStorage.setItem(TOKEN_KEY, token);

    // Fetch user info
    const user = await fetchUser();

    // Clear token from URL
    const url = new URL(window.location.href);
    url.searchParams.delete('token');
    history.replaceState(null, '', url.pathname + url.search);

    return user;
}

/**
 * Initialize auth - check for token in URL (OAuth callback).
 * Call this on app startup.
 */
export async function init() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');

    if (token) {
        // OAuth callback
        await handleCallback(token);
    } else if (isAuthenticated()) {
        // Already have token, fetch user if not cached
        if (!getUser()) {
            await fetchUser();
        }
    }
}

export default {
    isAuthenticated,
    getToken,
    getAuthHeaders,
    getUser,
    fetchUser,
    updateCachedUser,
    getLastFetchError,
    clearLastFetchError,
    login,
    logout,
    handleCallback,
    init,
};
