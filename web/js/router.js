/**
 * Simple History API router for client-side navigation.
 */

const routes = [];
let currentCleanup = null;

/**
 * Register a route.
 * @param {string} path - Route path with optional :params (e.g., '/play/:gameId')
 * @param {Function} handler - Async function called when route matches
 * @param {Object} options - { auth: boolean } - requires authentication
 */
export function addRoute(path, handler, options = {}) {
    const paramNames = [];
    const pattern = path.replace(/:(\w+)/g, (_, name) => {
        paramNames.push(name);
        return '([^/]+)';
    });
    const regex = new RegExp(`^${pattern}$`);

    routes.push({ path, regex, paramNames, handler, ...options });
}

/**
 * Navigate to a path.
 * @param {string} path - The path to navigate to
 * @param {Object} options - { replace: boolean } - use replaceState instead of pushState
 */
export function navigate(path, options = {}) {
    if (options.replace) {
        history.replaceState(null, '', path);
    } else {
        history.pushState(null, '', path);
    }
    handleRoute();
}

/**
 * Get current path.
 */
export function getCurrentPath() {
    return window.location.pathname;
}

/**
 * Get query parameters.
 */
export function getQueryParams() {
    return Object.fromEntries(new URLSearchParams(window.location.search));
}

/**
 * Match current path against registered routes and execute handler.
 */
async function handleRoute() {
    const path = getCurrentPath();
    const query = getQueryParams();

    // Run cleanup from previous route if any
    if (currentCleanup) {
        try {
            await currentCleanup();
        } catch (e) {
            console.error('Route cleanup error:', e);
        }
        currentCleanup = null;
    }

    for (const route of routes) {
        const match = path.match(route.regex);
        if (match) {
            // Extract params
            const params = {};
            route.paramNames.forEach((name, i) => {
                params[name] = decodeURIComponent(match[i + 1]);
            });

            // Check auth requirement
            if (route.auth) {
                const { isAuthenticated } = await import('./auth.js');
                if (!isAuthenticated()) {
                    // Store return URL and redirect to landing
                    sessionStorage.setItem('auth_return_url', path);
                    navigate('/', { replace: true });
                    return;
                }
            }

            // Execute handler
            try {
                const cleanup = await route.handler({ params, query });
                if (typeof cleanup === 'function') {
                    currentCleanup = cleanup;
                }
            } catch (e) {
                console.error('Route handler error:', e);
            }
            return;
        }
    }

    // No route matched - show 404 or redirect to home
    console.warn(`No route matched for path: ${path}`);
    navigate('/', { replace: true });
}

/**
 * Initialize the router.
 * Call this after all routes are registered.
 */
export function init() {
    // Handle browser back/forward
    window.addEventListener('popstate', handleRoute);

    // Intercept link clicks for SPA navigation
    document.addEventListener('click', e => {
        const link = e.target.closest('a[href]');
        if (!link) return;

        const href = link.getAttribute('href');

        // Skip external links, hash links, and links with target
        if (
            !href ||
            href.startsWith('http') ||
            href.startsWith('#') ||
            link.hasAttribute('target') ||
            link.hasAttribute('download')
        ) {
            return;
        }

        // Handle internal navigation
        e.preventDefault();
        navigate(href);
    });

    // Initial route
    handleRoute();
}

export default {
    addRoute,
    navigate,
    getCurrentPath,
    getQueryParams,
    init,
};
