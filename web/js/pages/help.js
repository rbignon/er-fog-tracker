/**
 * Help page - Guide for setting up and using the Fog Tracker.
 */

/**
 * Show the help page.
 */
export function show() {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById('help-page').classList.remove('hidden');
    document.body.classList.remove('graph-mode');
}

/**
 * Initialize help page event handlers.
 */
export function init() {
    // Toggle FAQ answers
    document.querySelectorAll('.faq-question').forEach(question => {
        question.addEventListener('click', () => {
            const item = question.closest('.faq-item');
            item.classList.toggle('open');
        });
    });
}

/**
 * Route handler for help page.
 */
export function handleRoute() {
    show();
}
