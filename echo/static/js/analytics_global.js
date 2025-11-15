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

  function initNavbarTracking(){
    try {
      var links = document.querySelectorAll('.nav-links .generic-nav-btn');
      links.forEach(function(link){
        link.addEventListener('click', function(){
          var label = (link.textContent || '').trim().toLowerCase();
          var action = null;
          if (label === 'search') action = 'nav_search';
          else if (label === 'about') action = 'nav_about';
          else if (label === 'tag library') action = 'nav_tag_library';
          else if (label === 'statistics') action = 'nav_statistics';
          if (!action) return;
          postClick(action, null, { href: link.getAttribute('href') || null });
        });
      });
    } catch (e) {}
  }

  function initBulkDownloadTracking(){
    try {
      var directBtn = document.getElementById('bulkDirectAllBtn');
      var selectAllBtn = document.getElementById('bulkSelectAllBtn');
      if (directBtn) {
        directBtn.addEventListener('click', function(){
          postClick('bulk_direct_all', null, null);
        });
      }
      if (selectAllBtn) {
        selectAllBtn.addEventListener('click', function(){
          postClick('bulk_select_all', null, null);
        });
      }
    } catch (e) {}
  }

  function initPaginationTracking(){
    try {
      document.addEventListener('click', function(e){
        var t = e.target;
        if (!t) return;
        var a = t.closest && t.closest('.pagination a');
        if (!a) return;
        var href = a.getAttribute('href') || null;
        postClick('pagination', null, { href: href });
      });
    } catch (e) {}
  }

  function initUserMenuTracking(){
    try {
      var dropdown = document.getElementById('profileDropdown');
      if (!dropdown) return;
      dropdown.addEventListener('click', function(e){
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
            postClick(action, null, { href: href });
          }
        }
        var btn = t.closest && t.closest('button');
        if (btn) {
          var bl = (btn.textContent || '').trim().toLowerCase();
          if (bl === 'logout') {
            postClick('nav_logout', null, null);
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
        btn.addEventListener('click', function(){
          var label = (btn.textContent || '').trim().toLowerCase();
          var action = null;
          if (label.indexOf('farm') !== -1) action = 'preset_farm_maps';
          else if (label.indexOf('favorites') !== -1) action = 'preset_favorites';
          if (!action) return;
          postClick(action, null, null);
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


