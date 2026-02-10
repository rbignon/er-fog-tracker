/**
 * Shared HTML sanitization utility.
 */

/**
 * Escape a string for safe insertion into HTML.
 * Uses the browser's built-in textContent encoding.
 * @param {*} str - The value to escape
 * @returns {string} HTML-safe string
 */
export function escapeHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}
