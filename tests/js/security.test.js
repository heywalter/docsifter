const assert = require('node:assert/strict');
const test = require('node:test');

const { escapeHtml } = require('../../src/docsifter/static/js/security.js');

test('escapeHtml is safe in text and quoted attribute contexts', () => {
    assert.equal(
        escapeHtml('<img src="x" onerror=\'alert(1)\'>&'),
        '&lt;img src=&quot;x&quot; onerror=&#39;alert(1)&#39;&gt;&amp;'
    );
});

test('escapeHtml handles nullish and non-string values', () => {
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(undefined), '');
    assert.equal(escapeHtml(42), '42');
});
