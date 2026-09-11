const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function element(properties = {}) {
  const listeners = new Map();
  return Object.assign({ style: {}, innerHTML: '' }, properties, {
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(callback);
    },
    dispatch(name, event = {}) {
      for (const callback of listeners.get(name) || []) callback(event);
    },
  });
}

function browser(includeBots = false) {
  const requests = [];
  const intervals = [];
  const timeouts = [];
  const elements = {
    adminIncludeLikelyBots: element({ checked: false }),
    adminEventsMoreBtn: element(),
    adminLatestEvents: element(),
    adminTagForm: element(),
    adminTagInput: element({ value: 'streams' }),
    adminTagMode: element({ value: 'std' }),
  };
  const window = {
    location: new URL('https://echosu.test/statistics/?tab=admin&user=someone' + (includeBots ? '&include_likely_bots=1' : '')),
  };
  const context = vm.createContext({
    window, URL, URLSearchParams,
    document: {
      hidden: false,
      getElementById: id => elements[id] || null,
      querySelector: selector => selector === '.tab-section.is-active' ? { getAttribute: () => 'admin' } : null,
      querySelectorAll: () => [],
      createElement: () => element({ firstChild: null }),
    },
    fetch: async url => {
      const parsed = new URL(url);
      requests.push(parsed);
      const payload = parsed.pathname.endsWith('/latest-events/')
        ? { html: '<div>Event</div>', has_more: true }
        : { searches: {}, uniques: {}, tag: 'streams', mode: parsed.searchParams.get('mode') };
      return { json: async () => payload };
    },
    setInterval: (callback, delay) => intervals.push({ callback, delay }),
    setTimeout: (callback, delay) => timeouts.push({ callback, delay }),
    clearInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/statistics.js'), 'utf8'), context);
  window.initStatisticsTabs({});
  return { window, elements, requests, intervals, timeouts };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

for (const includeBots of [false, true]) {
  test(`all admin requests retain the likely-bot filter (include=${includeBots})`, async () => {
    const app = browser(includeBots);
    await settle();
    assert.equal(app.elements.adminIncludeLikelyBots.checked, includeBots);
    assert.equal(app.requests.length, 1);
    assert.equal(app.requests[0].pathname, '/statistics/admin-data/');

    app.timeouts.find(timer => timer.delay === 100).callback();
    await settle();
    assert.equal(app.requests.at(-1).pathname, '/statistics/latest-events/');
    assert.equal(app.elements.adminLatestEvents.innerHTML, '<div>Event</div>');

    app.intervals.find(timer => timer.delay === 30000).callback();
    await settle();
    assert.equal(app.requests.at(-1).pathname, '/statistics/latest-events/');
    app.intervals.find(timer => timer.delay === 3600000).callback();
    await settle();
    assert.equal(app.requests.at(-1).pathname, '/statistics/admin-data/');

    app.elements.adminTagMode.value = 'mania';
    app.elements.adminTagForm.dispatch('submit', { preventDefault() {} });
    await settle();
    assert.equal(app.requests.at(-1).pathname, '/statistics/admin-tag/');
    assert.equal(app.requests.at(-1).searchParams.get('tag'), 'streams');
    assert.equal(app.requests.at(-1).searchParams.get('mode'), 'mania');

    app.elements.adminEventsMoreBtn.dispatch('click');
    await settle();
    assert.equal(app.requests.at(-1).pathname, '/statistics/latest-events/');
    assert.equal(app.requests.at(-1).searchParams.get('offset'), '30');
    assert.equal(app.requests.length, 6);
    for (const request of app.requests) {
      assert.equal(request.searchParams.get('include_likely_bots'), includeBots ? '1' : '0');
    }
  });
}

test('changing the toggle reloads the admin tab with the chosen filter and preserves other parameters', () => {
  const app = browser();
  app.elements.adminIncludeLikelyBots.checked = true;
  app.elements.adminIncludeLikelyBots.dispatch('change');
  assert.equal(app.window.location.searchParams.get('include_likely_bots'), '1');
  assert.equal(app.window.location.searchParams.get('tab'), 'admin');
  assert.equal(app.window.location.searchParams.get('user'), 'someone');

  app.elements.adminIncludeLikelyBots.checked = false;
  app.elements.adminIncludeLikelyBots.dispatch('change');
  assert.equal(app.window.location.searchParams.has('include_likely_bots'), false);
  assert.equal(app.window.location.searchParams.get('tab'), 'admin');
  assert.equal(app.window.location.searchParams.get('user'), 'someone');
});
