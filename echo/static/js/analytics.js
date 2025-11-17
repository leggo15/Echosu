(function(){
  function getCookie(name){
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }
  function getCsrf(){
    try {
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) return meta.content;
    } catch (e) {}
    return getCookie('csrftoken') || getCookie('CSRF-TOKEN') || '';
  }
  async function postJson(url, body){
    var headers = {'Accept':'application/json','Content-Type':'application/json'};
    var csrf = getCsrf();
    if (csrf) headers['X-CSRFToken'] = csrf;
    try {
      var resp = await fetch(url, {method:'POST', credentials:'same-origin', headers, body: JSON.stringify(body || {})});
      return await resp.json();
    } catch (e) {
      return { ok: false, error: String(e && e.message || e) };
    }
  }

  function parseAnalyticsContext(){
    try {
      var el = document.getElementById('analytics-context');
      if (!el) return null;
      return JSON.parse(el.textContent || '{}');
    } catch (e) { return null; }
  }

  function getBeatmapIdFromEl(el){
    try {
      var wrapper = el.closest('.beatmap-card-wrapper');
      if (!wrapper) return null;
      return wrapper.getAttribute('data-beatmap-id') || null;
    } catch (e) { return null; }
  }

  function detectAction(el){
    if (!el) return null;
    if (el.classList.contains('find-similar-btn')) return 'find_similar';
    if (el.classList.contains('mini-map-links')) {
      var t = (el.textContent || '').trim().toLowerCase();
      if (t === 'direct') return 'direct';
      if (t === 'beatconnect') return 'beatconnect';
      return 'mini_map_link';
    }
    if (el.classList.contains('beatmap-link')) {
      var href = (el.getAttribute('href') || '').toLowerCase();
      if (href.indexOf('osu.ppy.sh/beatmapsets') !== -1) return 'view_on_osu';
      if (href.indexOf('/beatmap_detail/') !== -1) return 'view_details';
      return 'beatmap_link';
    }
    if (el.classList.contains('bulk-select-checkbox')) return 'bulk_select_toggle';
    return null;
  }

  async function init(){
    var ctx = parseAnalyticsContext();
    if (!ctx) return;
    // Only log when there is a real search interaction (including empty query with filters)
    var searchResp = await postJson('/analytics/log/search/', {
      query: ctx.query || '',
      tags: Array.isArray(ctx.tags) ? ctx.tags : null,
      results_count: typeof ctx.results_count === 'number' ? ctx.results_count : (ctx.results_total || null),
      sort: ctx.sort || '',
      predicted_mode: ctx.predicted_mode || '',
      mode: ctx.mode || '',
      flags: ctx.flags || null
    });
    if (!searchResp || !searchResp.ok) return;
    var searchEventId = searchResp.event_id || null;

    // Delegate click logging within the search results
    var container = document.querySelector('.search-results') || document;
    container.addEventListener('click', function(e){
      try {
        var t = e.target;
        var a = t.closest('a'); // anchors on tag cards
        var btn = a || t.closest('.find-similar-btn') || t.closest('.beatmap-link') || t.closest('.mini-map-links');
        if (!btn) return;
        var action = detectAction(btn);
        if (!action) return;
        var beatmapId = getBeatmapIdFromEl(btn);
        var payload = {
          action: action,
          beatmap_id: beatmapId,
          search_event_id: searchEventId,
          meta: {
            tag_name: btn.dataset && (btn.dataset.tagName || null),
            href: btn.getAttribute && btn.getAttribute('href') || null
          }
        };
        // Defer logging to avoid interfering with default link behavior
        setTimeout(function(){ postJson('/analytics/log/click/', payload); }, 0);
      } catch (err) {}
    }, { passive: true });

    // Bulk checkbox changes
    container.addEventListener('change', function(e){
      var t = e.target;
      if (!t || !t.classList || !t.classList.contains('bulk-select-checkbox')) return;
      var beatmapId = getBeatmapIdFromEl(t);
      postJson('/analytics/log/click/', {
        action: 'bulk_select_toggle',
        beatmap_id: beatmapId,
        search_event_id: searchEventId,
        meta: { checked: !!t.checked }
      });
    });
  }

  window.initSearchAnalytics = init;
})();

