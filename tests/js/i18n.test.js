const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// A text node the way i18n sees one: a value, and a parent it can ask whether
// this subtree is off limits.
function textNode(value) {
  const node = { nodeType: 3, nodeValue: value };
  node.parentElement = { closest: () => null };
  return node;
}

function loadI18n(textNodes = []) {
  const storage = new Map();
  const body = {
    nodeType: 1,
    matches: () => false,
    querySelectorAll: () => [],
  };
  const document = {
    body,
    documentElement: { lang: 'zh-CN' },
    title: 'DocSifter',
    addEventListener: () => {},
    createTreeWalker: () => {
      let index = 0;
      return { nextNode: () => (index < textNodes.length ? textNodes[index++] : null) };
    },
    getElementById: () => null,
    querySelectorAll: () => [],
  };
  const window = {
    dispatchEvent: () => {},
  };
  const context = {
    console,
    CustomEvent: class CustomEvent {},
    document,
    localStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    },
    MutationObserver: class MutationObserver {
      observe() {}
    },
    Node: {
      DOCUMENT_FRAGMENT_NODE: 11,
      DOCUMENT_NODE: 9,
      ELEMENT_NODE: 1,
      TEXT_NODE: 3,
    },
    NodeFilter: { SHOW_TEXT: 4 },
    window,
  };
  window.document = document;

  const source = fs.readFileSync(
    path.join(__dirname, '../../src/docsifter/static/js/i18n.js'),
    'utf8',
  );
  vm.runInNewContext(source, context);
  return { i18n: window.I18n, storage, document };
}

function loadIndexHtmlChineseSegments() {
  const html = fs
    .readFileSync(path.join(__dirname, '../../src/docsifter/templates/index.html'), 'utf8')
    .replace(/<script[\s\S]*?<\/script>/g, '')
    .replace(/<style[\s\S]*?<\/style>/g, '');

  const segments = [...html.matchAll(/>([^<>]+)</g)]
    .map((match) => match[1].trim())
    .filter((text) => /[\u4e00-\u9fa5]/.test(text));

  return [...new Set(segments)];
}

test('language switching updates the active locale without runtime errors', () => {
  const { i18n, storage, document } = loadI18n();

  i18n.setLanguage('en');
  assert.equal(i18n.getLanguage(), 'en');
  assert.equal(storage.get('docsifter.language'), 'en');
  assert.equal(document.documentElement.lang, 'en-US');

  i18n.setLanguage('zh');
  assert.equal(i18n.getLanguage(), 'zh');
  assert.equal(document.documentElement.lang, 'zh-CN');
});


test('adjacent sentences keep the space English needs between them', () => {
  // One <p> in index.html holds two Chinese sentences. They are two dictionary
  // keys, and 。 needs no space after it, so splicing them one at a time used
  // to produce "...1.5B small model.The current selection...".
  const { i18n } = loadI18n();
  i18n.setLanguage('en');

  const source =
    '规则预览模式无需模型；安装模型依赖后，推荐先使用 1.5B 小模型进行 AI 审查。' +
    '保存 Webhook 配置时会记录当前选择。';
  const translated = i18n.translateText(source);

  assert.match(translated, /small model\. The current selection/);
  assert.doesNotMatch(translated, /[a-z]\.[A-Z]/);
});

test('no template string translates into a run-on sentence', () => {
  const { i18n } = loadI18n();
  i18n.setLanguage('en');

  const offenders = loadIndexHtmlChineseSegments()
    .map((segment) => i18n.translateText(segment))
    .filter((translated) => /[a-z][.,;:][A-Za-z]/.test(translated));

  assert.deepEqual(offenders, [], 'these translations weld two sentences together');
});

test('every Chinese string in the template has an English translation', () => {
  const { i18n } = loadI18n();
  i18n.setLanguage('en');

  const untranslated = loadIndexHtmlChineseSegments().filter((segment) =>
    /[\u4e00-\u9fa5]/.test(i18n.translateText(segment)),
  );

  assert.deepEqual(untranslated, [], 'these strings would stay Chinese in the English UI');
});

test('splicing does not insert a space in front of Chinese text', () => {
  const { i18n } = loadI18n();
  i18n.setLanguage('zh');

  const source = '开始处理';
  assert.equal(i18n.translateText(source), source);
});


test('a label rendered in English still returns to Chinese', () => {
  // app.js writes some labels through t(), so a node created while the UI is in
  // English arrives already translated. Recording that English text as its
  // source used to strand it: switching back to Chinese left it in English.
  const node = textNode('Rule preview mode');
  const { i18n } = loadI18n([node]);

  i18n.setLanguage('en');
  assert.equal(node.nodeValue, 'Rule preview mode');

  i18n.setLanguage('zh');
  assert.equal(node.nodeValue, '规则预览模式');
});

test('a label first seen in Chinese round-trips both ways', () => {
  const node = textNode('规则预览模式');
  const { i18n } = loadI18n([node]);

  i18n.setLanguage('en');
  assert.equal(node.nodeValue, 'Rule preview mode');

  i18n.setLanguage('zh');
  assert.equal(node.nodeValue, '规则预览模式');
});

test('an ambiguous translation is left alone rather than guessed', () => {
  // "Completed" is produced by both 完成时间 and 已完成. Choosing one would put
  // the wrong word on screen, so such a node keeps the text it already has.
  const node = textNode('Completed');
  const { i18n } = loadI18n([node]);

  i18n.setLanguage('en');
  i18n.setLanguage('zh');
  assert.equal(node.nodeValue, 'Completed');
});

test('text that is not a translation is left untouched', () => {
  const node = textNode('shibing624/chinese-text-correction-1.5b');
  const { i18n } = loadI18n([node]);

  i18n.setLanguage('en');
  i18n.setLanguage('zh');
  assert.equal(node.nodeValue, 'shibing624/chinese-text-correction-1.5b');
});
