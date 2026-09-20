const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// app.js wraps window.fetch so that every mutating request carries
// X-DocSifter-Request. The server rejects a mutation without it (see
// docsifter/web/security.py), which is what stops a cross-site form post, so
// the header has to survive whichever way a caller passes its options.
function loadApp() {
  const calls = [];
  const nativeFetch = (resource, options) => {
    calls.push({ resource, options });
    return Promise.resolve({ ok: true });
  };

  const window = {
    fetch: nativeFetch,
    addEventListener: () => {},
  };
  const document = {
    addEventListener: () => {},
    getElementById: () => null,
    querySelectorAll: () => [],
    querySelector: () => null,
    body: { appendChild: () => {}, removeChild: () => {} },
  };
  window.document = document;

  const context = {
    console,
    document,
    window,
    Headers: globalThis.Headers,
    localStorage: { getItem: () => null, setItem: () => {} },
    setInterval: () => 0,
    setTimeout: () => 0,
  };

  const source = fs.readFileSync(
    path.join(__dirname, '../../src/docsifter/static/js/app.js'),
    'utf8',
  );
  vm.runInNewContext(source, context);
  return { fetch: window.fetch, calls };
}

test('mutating requests carry the request-verification header', async () => {
  const { fetch, calls } = loadApp();

  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    await fetch('/api/whitelist', { method });
  }

  assert.equal(calls.length, 4);
  for (const call of calls) {
    assert.equal(call.options.headers.get('X-DocSifter-Request'), '1');
  }
});

test('the header is added without dropping the caller\'s own headers', async () => {
  const { fetch, calls } = loadApp();

  await fetch('/api/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });

  const [call] = calls;
  assert.equal(call.options.headers.get('Content-Type'), 'application/json');
  assert.equal(call.options.headers.get('X-DocSifter-Request'), '1');
  assert.equal(call.options.body, '{}');
});

test('reads are passed through untouched', async () => {
  const { fetch, calls } = loadApp();

  await fetch('/api/history');

  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers, undefined);
});
