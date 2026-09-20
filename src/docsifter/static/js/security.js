(function (root) {
    const HTML_ENTITIES = Object.freeze({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    });

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (character) => HTML_ENTITIES[character]);
    }

    const api = Object.freeze({ escapeHtml });
    root.DocSifterSecurity = api;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
})(typeof window !== 'undefined' ? window : globalThis);
