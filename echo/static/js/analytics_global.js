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

  async function postClick(action, beatmapId, meta){
    var headers = {'Accept':'application/json','Content-Type':'application/json'};
    var csrf = getCsrf();
    if (csrf) headers['X-CSRFToken'] = csrf;
    var body = {
      action: action,
      beatmap_id: beatmapId || null,
      search_event_id: null,
      meta: meta || null
    };
    try {
      await fetch('/analytics/log/click/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: headers,
        body: JSON.stringify(body)
      });
    } catch (e) {
      // Swallow errors; analytics must never break navigation
    }
  }

  function addPassiveListener(el, type, handler){
    if (!el) return;
    try {
      el.addEventListener(type, handler, { passive: true });
    } catch (e) {
      el.addEventListener(type, handler);
    }
  }

  function initNavbarTracking(){
    try {
      var links = document.querySelectorAll('.nav-links .generic-nav-btn');
      links.forEach(function(link){
        addPassiveListener(link, 'click', function(){
          var label = (link.textContent || '').trim().toLowerCase();
          var action = null;
          if (label === 'search') action = 'nav_search';
          else if (label === 'about') action = 'nav_about';
          else if (label === 'tag library') action = 'nav_tag_library';
          else if (label === 'statistics') action = 'nav_statistics';
          if (!action) return;
          setTimeout(function(){
            postClick(action, null, { href: link.getAttribute('href') || null });
          }, 0);
        });
      });
    } catch (e) {}
  }

  function initBulkDownloadTracking(){
    try {
      var directBtn = document.getElementById('bulkDirectAllBtn');
      var selectAllBtn = document.getElementById('bulkSelectAllBtn');
      if (directBtn) {
        addPassiveListener(directBtn, 'click', function(){
          setTimeout(function(){ postClick('bulk_direct_all', null, null); }, 0);
        });
      }
      if (selectAllBtn) {
        addPassiveListener(selectAllBtn, 'click', function(){
          setTimeout(function(){ postClick('bulk_select_all', null, null); }, 0);
        });
      }
    } catch (e) {}
  }

  function initPaginationTracking(){
    try {
      addPassiveListener(document, 'click', function(e){
        var t = e.target;
        if (!t) return;
        var a = t.closest && t.closest('.pagination a');
        if (!a) return;
        var href = a.getAttribute('href') || null;
        setTimeout(function(){ postClick('pagination', null, { href: href }); }, 0);
      });
    } catch (e) {}
  }

  function initUserMenuTracking(){
    try {
      var dropdown = document.getElementById('profileDropdown');
      if (!dropdown) return;
      addPassiveListener(dropdown, 'click', function(e){
        var t = e.target;
        if (!t) return;
        var a = t.closest && t.closest('a');
        if (a) {
          var label = (a.textContent || '').trim().toLowerCase();
          var href = a.getAttribute('href') || null;
          var action = null;
          if (label === 'settings') action = 'nav_settings';
          else if (label === 'edit tags') action = 'nav_edit_tags';
          if (action) {
            setTimeout(function(){ postClick(action, null, { href: href }); }, 0);
          }
        }
        var btn = t.closest && t.closest('button');
        if (btn) {
          var bl = (btn.textContent || '').trim().toLowerCase();
          if (bl === 'logout') {
            setTimeout(function(){ postClick('nav_logout', null, null); }, 0);
          }
        }
      });
    } catch (e) {}
  }

  function init(){
    initNavbarTracking();
    initBulkDownloadTracking();
    initPaginationTracking();
    initUserMenuTracking();
    // Preset search buttons on search_results page
    try {
      var presets = document.querySelectorAll('.preset-button');
      presets.forEach(function(btn){
        addPassiveListener(btn, 'click', function(){
          var label = (btn.textContent || '').trim().toLowerCase();
          var action = null;
          if (label.indexOf('farm') !== -1) action = 'preset_farm_maps';
          else if (label.indexOf('favorites') !== -1) action = 'preset_favorites';
          if (!action) return;
          setTimeout(function(){ postClick(action, null, null); }, 0);
        });
      });
    } catch (e) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();


