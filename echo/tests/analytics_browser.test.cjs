const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function eventTarget(properties = {}) {
  const listeners = new Map();
  return Object.assign(properties, {
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(callback);
    },
    removeEventListener(name, callback) {
      if (listeners.has(name)) listeners.get(name).delete(callback);
    },
    dispatch(name, event = {}) {
      for (const callback of [...(listeners.get(name) || [])]) callback(event);
    },
  });
}

function browser({ automated = false, hidden = false, prerendering = false, query = 'streams' } = {}) {
  const requests = [];
  const navLink = eventTarget({
    textContent: 'Search',
    getAttribute: () => '/',
  });
  const card = { getAttribute: () => '123' };
  const document = eventTarget({
    readyState: 'complete',
    visibilityState: hidden ? 'hidden' : 'visible',
    prerendering,
    cookie: 'csrftoken=test-token',
    getElementById(id) {
      return id === 'analytics-context' ? { textContent: JSON.stringify({ query, tags: ['streams'], results_count: 1 }) } : null;
    },
    querySelector: () => null,
    querySelectorAll(selector) {
      if (selector === '.nav-links .generic-nav-btn') return [navLink];
      if (selector === '.beatmap-card-wrapper[data-beatmap-id]') return [card];
      return [];
    },
  });
  const window = { navigator: { webdriver: automated }, location: { search: '' } };
  const context = vm.createContext({
    document, window, URLSearchParams, setTimeout, clearTimeout,
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { json: async () => ({ ok: true, event_id: 'test-search-id' }) };
    },
  });
  for (const file of ['analytics_guard.js', 'analytics_global.js', 'analytics.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js', file), 'utf8'), context, { filename: file });
  }
  return { document, window, requests, navLink };
}

const settle = () => new Promise(resolve => setTimeout(resolve, 10));

test('visible browser records a search and impressions once despite repeated initialization', async () => {
  const app = browser();
  app.window.initSearchAnalytics();
  app.window.initSearchAnalytics();
  await settle();
  assert.equal(app.requests.filter(r => r.url === '/analytics/log/search/').length, 1);
  assert.equal(app.requests.filter(r => r.url === '/analytics/log/impressions/').length, 1);
});

test('WebDriver sessions produce neither searches, impressions nor navbar clicks', async () => {
  const app = browser({ automated: true });
  app.window.initSearchAnalytics();
  app.navLink.dispatch('click');
  await settle();
  assert.deepEqual(app.requests, []);
});

test('background search waits until visible and is not recounted on later tab switches', async () => {
  const app = browser({ hidden: true });
  app.window.initSearchAnalytics();
  app.window.initSearchAnalytics();
  await settle();
  assert.equal(app.requests.length, 0);
  app.document.visibilityState = 'visible';
  app.document.dispatch('visibilitychange');
  await settle();
  assert.equal(app.requests.length, 2);
  app.document.visibilityState = 'hidden';
  app.document.dispatch('visibilitychange');
  app.document.visibilityState = 'visible';
  app.document.dispatch('visibilitychange');
  await settle();
  assert.equal(app.requests.length, 2);
});

test('prerendered search is recorded only on activation', async () => {
  const app = browser({ prerendering: true });
  app.window.initSearchAnalytics();
  await settle();
  assert.equal(app.requests.length, 0);
  app.document.prerendering = false;
  app.document.dispatch('prerenderingchange');
  await settle();
  assert.equal(app.requests.length, 2);
});

test('ordinary navbar interactions remain counted', async () => {
  const app = browser();
  app.navLink.dispatch('click');
  await settle();
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].body.action, 'nav_search');
});

test('empty searches still do not produce search events or map impressions', async () => {
  const app = browser({ query: '' });
  app.window.initSearchAnalytics();
  await settle();
  assert.deepEqual(app.requests, []);
});
