/**
 * Landing page - Login with Twitch or use offline mode.
 */

import * as Auth from '../auth.js';
import { navigate } from '../router.js';
import * as State from '../state.js';
import { loadOfflineGame } from '../ui.js';

/**
 * Show the landing page.
 */
export function show() {
    // Hide all pages, show landing
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('landing-page').classList.remove('hidden');
    document.body.classList.remove('graph-mode');
}

/**
 * Initialize landing page event handlers.
 */
export function init() {
    const loginBtn = document.getElementById('login-twitch-btn');

    loginBtn.addEventListener('click', () => {
        Auth.login();
    });
}

/**
 * Route handler for landing page.
 */
export async function handleRoute({ query }) {
    // Check for OAuth callback token
    if (query.token) {
        const user = await Auth.handleCallback(query.token);
        if (user) {
            // Check for stored return URL
            const returnUrl = sessionStorage.getItem('auth_return_url');
            sessionStorage.removeItem('auth_return_url');
            navigate(returnUrl || '/dashboard', { replace: true });
            return;
        }
    }

    // If already authenticated and no pending error, redirect to dashboard
    if (Auth.isAuthenticated() && !Auth.getLastFetchError()) {
        navigate('/dashboard', { replace: true });
        return;
    }

    // Check for offline mode
    if (query.offline === 'true') {
        // If a specific seed is requested, try to load it
        if (query.seed) {
            State.setBackendMode('offline');
            if (loadOfflineGame(query.seed)) {
                // Game loaded successfully - handleOfflineGraphLoaded will be called via graphDataChanged event
                return;
            }
        }

        // No seed requested or failed to load - show upload screen
        State.setBackendMode('offline');
        document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
        document.getElementById('upload-screen').classList.remove('hidden');
        return;
    }

    show();
}

export default {
    show,
    init,
    handleRoute,
};
