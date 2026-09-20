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


// The dashboard cards are fed by /api/current-stats, which names its numbers
// differently from /stats. Reading only the /stats names left "Valid
// Corrections" and "Defect Rate" on zero for every install, and `|| 0` meant
// nothing ever surfaced the mismatch.
function loadAppClass() {
  const source = fs.readFileSync(
    path.join(__dirname, '../../src/docsifter/static/js/app.js'),
    'utf8',
  );
  const context = {
    console,
    window: { fetch: () => Promise.resolve({ ok: true }), addEventListener: () => {} },
    document: { addEventListener: () => {}, getElementById: () => null, querySelectorAll: () => [] },
    Headers: globalThis.Headers,
    localStorage: { getItem: () => null, setItem: () => {} },
    setInterval: () => 0,
    setTimeout: () => 0,
  };
  context.window.document = context.document;
  vm.runInNewContext(source + '\n;globalThis.__DocSifterApp = DocumentReviewerApp;', context);
  return { AppClass: context.__DocSifterApp, context };
}

function renderStats(stats) {
  const { AppClass, context } = loadAppClass();
  const cards = { totalFiles: {}, validChanges: {}, defectRate: {} };
  context.document.getElementById = (id) => cards[id];
  AppClass.prototype.updateStatsDisplay.call({}, stats);
  return cards;
}

test('the dashboard renders the numbers /api/current-stats actually returns', () => {
  const cards = renderStats({ total_files: 2, total_changes: 6, avg_defect_rate: 11.01 });

  assert.equal(cards.totalFiles.textContent, 2);
  assert.equal(cards.validChanges.textContent, 6);
  assert.equal(cards.defectRate.textContent, '11.0‰');
});

test('the dashboard also renders the /stats shape', () => {
  const cards = renderStats({
    total_files: 9,
    valid_changes: 41,
    defect_rate_per_thousand: 3.25,
  });

  assert.equal(cards.totalFiles.textContent, 9);
  assert.equal(cards.validChanges.textContent, 41);
  assert.equal(cards.defectRate.textContent, '3.3‰');
});

test('an empty stats payload reads as zero rather than NaN', () => {
  const cards = renderStats({});

  assert.equal(cards.totalFiles.textContent, 0);
  assert.equal(cards.validChanges.textContent, 0);
  assert.equal(cards.defectRate.textContent, '0.0‰');
});
