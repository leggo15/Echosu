// Core JS: site-wide utilities only
(function() {
  // Profile dropdown toggle
  document.addEventListener('DOMContentLoaded', function() {
    var profileMenuButton = document.getElementById('profileMenuButton');
    if (profileMenuButton) {
      profileMenuButton.addEventListener('click', function(e) {
        e.stopPropagation();
        var dropdown = document.getElementById('profileDropdown');
        if (dropdown) {
          var willOpen = dropdown.style.display !== 'block';
          dropdown.style.display = willOpen ? 'block' : 'none';
          try { profileMenuButton.setAttribute('aria-expanded', willOpen ? 'true' : 'false'); } catch (err) {}
        }
      });
      window.addEventListener('click', function(event) {
        if (!event.target.closest || !event.target.closest('#profileMenuButton')) {
          var dropdowns = document.getElementsByClassName('dropdown-content');
          for (var i = 0; i < dropdowns.length; i++) {
            var openDropdown = dropdowns[i];
            if (openDropdown.style.display === 'block') {
              openDropdown.style.display = 'none';
              try { profileMenuButton.setAttribute('aria-expanded', 'false'); } catch (err) {}
            }
          }
        }
      });
    }

    // Hamburger menu
    var hamburgerMenu = document.getElementById('hamburgerMenu');
    var navLinks = document.getElementById('navLinks');
    if (hamburgerMenu && navLinks) {
      hamburgerMenu.addEventListener('click', function() {
        navLinks.classList.toggle('active');
      });
    }

    // Theme toggle: persist preference in localStorage
    try {
      var THEME_KEY = 'theme-preference';
      var themeToggleBtn = document.getElementById('themeToggle');
      var docEl = document.documentElement;
      function applyTheme(theme) {
        if (theme === 'dark') {
          docEl.setAttribute('data-theme', 'dark');
          if (themeToggleBtn) themeToggleBtn.textContent = '☀️';
        } else {
          docEl.removeAttribute('data-theme');
          if (themeToggleBtn) themeToggleBtn.textContent = '🌙';
        }
      }
      // Initial: read saved or system preference
      var saved = null;
      try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
      if (saved === 'dark' || saved === 'light') {
        applyTheme(saved);
      } else {
        var prefersDark = false;
        try { prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches; } catch (e) {}
        applyTheme(prefersDark ? 'dark' : 'light');
      }
      if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function() {
          var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
          var next = isDark ? 'light' : 'dark';
          applyTheme(next);
          try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
        });
      }
    } catch (e) { /* no-op */ }

    // Auto-dismiss flash messages without affecting layout
    function bindFlashLifecycle(scope) {
      var list = (scope || document).querySelector('.messages');
      var items = list ? list.querySelectorAll('li') : [];
      if (!items.length) return;
      window.setTimeout(function() {
        items.forEach(function(item) { item.classList.add('fade-out'); });
      }, 2000);
      window.setTimeout(function() {
        items.forEach(function(item) {
          if (item && item.parentNode) { item.parentNode.removeChild(item); }
        });
      }, 3500);
    }
    bindFlashLifecycle(document);

    // Expose a reusable initializer so dynamically inserted cards get the defaults too
    function initAudioDefaults(root) {
      var scope = root || document;
      var audios = scope.querySelectorAll('audio');
      audios.forEach(function(audio) {
        // Prevent duplicate listeners
        if (audio.dataset.audioInitialized === '1') return;
        audio.dataset.audioInitialized = '1';
        try { audio.volume = 0.33; } catch (e) {}
        audio.addEventListener('play', function() {
          // Pause all other playing audio elements on the page
          document.querySelectorAll('audio').forEach(function(other) {
            if (other !== audio && !other.paused) {
              other.pause();
            }
          });
        });
      });
    }
    // Make globally accessible
    window.initAudioDefaults = initAudioDefaults;

    // Initialize for current document
    initAudioDefaults(document);

    // Mobile/Tablet side panels toggle
    try {
      var sideToggle = document.getElementById('sidePanelsToggle');
      var sidePanels = document.getElementById('sidePanels');
      if (sideToggle && sidePanels) {
        sideToggle.addEventListener('click', function() {
          var isOpen = sidePanels.classList.toggle('open');
          sideToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
      }
    } catch (e) { /* no-op */ }

    // Format beatmap length spans (Length: Ns -> Length: M:SS (N))
    var lengthSpans = document.querySelectorAll('.beatmap-length');
    lengthSpans.forEach(function(span) {
      var text = span.textContent.trim();
      // beatmap.total_length contains just the raw seconds number
      var totalSeconds = parseInt(text, 10);
      if (!isNaN(totalSeconds)) {
        var minutes = Math.floor(totalSeconds / 60);
        var seconds = totalSeconds % 60;
        var formatted = minutes + ':' + String(seconds).padStart(2, '0');
        span.textContent = 'Length: ' + formatted + ' (' + totalSeconds + ')';
      }
    });


    // Collapsible genres toggler used in beatmap cards
    var genreHeaders = document.querySelectorAll('h4.genres[aria-controls]');
    genreHeaders.forEach(function(header) {
      header.addEventListener('click', function() {
        var expanded = this.getAttribute('aria-expanded') === 'true';
        this.setAttribute('aria-expanded', (!expanded).toString());
        var contentId = this.getAttribute('aria-controls');
        var content = document.getElementById(contentId);
        if (content) {
          content.setAttribute('aria-hidden', expanded.toString());
          content.style.display = expanded ? 'none' : 'block';
          var arrow = this.querySelector('.arrow');
          if (arrow) {
            arrow.innerHTML = expanded ? '\u25BC' : '\u25B2';
          }
        }
      });
    });
  });

  // -----------------------------
  // Bulk Download Manager
  // -----------------------------
  const MAX_SELECTED = 30;
  const BULK_DIRECT_DELAY_MS = 10000; // delay between direct link calls
  const STORAGE_KEY = 'bulkSelectedMaps:v1';
  const bulkState = {
    // Map of beatmap_id -> { beatmapId, beatmapsetId, title }
    selected: new Map(),
  };

  function bulk_saveToStorage() {
    try {
      const items = Array.from(bulkState.selected.values());
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ items: items }));
    } catch (err) {
      // ignore storage errors
    }
  }

  function bulk_restoreFromStorage() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (!data || !Array.isArray(data.items)) return;
      bulkState.selected.clear();
      for (var i = 0; i < data.items.length && i < MAX_SELECTED; i++) {
        const it = data.items[i];
        if (it && it.beatmapId) {
          bulkState.selected.set(String(it.beatmapId), {
            beatmapId: String(it.beatmapId),
            beatmapsetId: it.beatmapsetId ? String(it.beatmapsetId) : '',
            title: it.title || null
          });
        }
      }
      bulk_renderList();
      bulk_syncCheckboxesFromState();
    } catch (err) {
      // ignore parse errors
    }
  }

  function bulk_getListEl() { return document.getElementById('bulkDownloadList'); }
  function bulk_getCountEl() { return document.getElementById('bulkSelectedCount'); }
  function bulk_getSelectAllBtn() { return document.getElementById('bulkSelectAllBtn'); }

  function bulk_updateSelectAllButton() {
    var btn = bulk_getSelectAllBtn();
    if (!btn) return;
    btn.textContent = bulkState.selected.size > 0 ? 'Deselect All' : 'Select All';
  }

  function bulk_clearAll() {
    bulkState.selected.clear();
    bulk_renderList();
    bulk_syncCheckboxesFromState();
  }

  function bulk_parsePaginationInfo(doc) {
    var info = { currentPage: 1, totalPages: 1 };
    try {
      var cur = doc.querySelector('.pagination .current');
      if (cur) {
        var m = cur.textContent.match(/Page\s+(\d+)\s+of\s+(\d+)/i);
        if (m) {
          info.currentPage = parseInt(m[1], 10) || 1;
          info.totalPages = parseInt(m[2], 10) || 1;
        }
      }
    } catch (e) { /* no-op */ }
    return info;
  }

  function bulk_collectFromContainer(container, remaining) {
    var added = 0;
    var checkboxes = container ? container.querySelectorAll('.bulk-select-checkbox') : [];
    for (var i = 0; i < checkboxes.length; i++) {
      if (added >= remaining) break;
      var cb = checkboxes[i];
      var id = String(cb.getAttribute('data-beatmap-id'));
      if (!id || bulkState.selected.has(id)) continue;
      var beatmapsetId = cb.getAttribute('data-beatmapset-id');
      var title = null;
      try {
        var wrapper = cb.closest('.beatmap-card-wrapper');
        var titleEl = wrapper ? wrapper.querySelector('.title') : null;
        title = titleEl ? titleEl.textContent.trim() : null;
      } catch (err) { /* no-op */ }
      bulk_select(id, beatmapsetId, title);
      // Also reflect check state if this checkbox is in the current DOM
      cb.checked = true;
      added++;
    }
    return added;
  }

  async function bulk_fetchPageAndSelect(page, remaining) {
    if (remaining <= 0) return 0;
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('page', String(page));
      var res = await fetch(url.toString(), { credentials: 'same-origin' });
      if (!res.ok) return 0;
      var html = await res.text();
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');
      var container = doc.querySelector('.search-results') || doc;
      var added = bulk_collectFromContainer(container, remaining);
      return added;
    } catch (e) { return 0; }
  }

  async function bulk_selectAllAcrossPages() {
    var remaining = MAX_SELECTED - bulkState.selected.size;
    if (remaining <= 0) return;
    // First, collect from current page DOM
    var container = document.querySelector('.search-results');
    var addedHere = bulk_collectFromContainer(container, remaining);
    remaining -= addedHere;
    if (remaining <= 0) return;
    // Then, iterate subsequent pages
    var info = bulk_parsePaginationInfo(document);
    var startPage = info.currentPage || 1;
    var totalPages = info.totalPages || 1;
    for (var p = startPage + 1; p <= totalPages && remaining > 0; p++) {
      /* eslint-disable no-await-in-loop */
      var addedThere = await bulk_fetchPageAndSelect(p, remaining);
      remaining -= addedThere;
      if (addedThere === 0) break; // nothing found/added
    }
  }
  function bulk_renderList() {
    const listEl = bulk_getListEl();
    const countEl = bulk_getCountEl();
    if (!listEl || !countEl) return;
    listEl.innerHTML = '';
    for (const [, item] of bulkState.selected) {
      const li = document.createElement('li');
      const text = document.createElement('span');
      text.textContent = `${item.title}`;
      const btn = document.createElement('button');
      btn.className = 'remove-item';
      btn.type = 'button';
      btn.textContent = '×';
      btn.setAttribute('aria-label', `Remove ${item.title || item.beatmapId}`);
      btn.addEventListener('click', function() { bulk_deselect(item.beatmapId); });
      li.appendChild(text);
      li.appendChild(btn);
      listEl.appendChild(li);
    }
    countEl.textContent = String(bulkState.selected.size);
    bulk_saveToStorage();
    bulk_updateSelectAllButton();
  }

  function bulk_select(beatmapId, beatmapsetId, title) {
    if (!beatmapId) return;
    if (!bulkState.selected.has(beatmapId)) {
      if (bulkState.selected.size >= MAX_SELECTED) {
        alert('You can select up to ' + MAX_SELECTED + ' maps.');
        return;
      }
      bulkState.selected.set(beatmapId, { beatmapId: beatmapId, beatmapsetId: beatmapsetId, title: title });
      bulk_renderList();
    }
  }

  function bulk_deselect(beatmapId) {
    if (bulkState.selected.delete(beatmapId)) {
      // Uncheck any matching checkbox on the page
      const checkbox = document.querySelector('.bulk-select-checkbox[data-beatmap-id="' + beatmapId + '"]');
      if (checkbox) checkbox.checked = false;
      bulk_renderList();
    }
  }

  function bulk_initCheckboxSync(root) {
    if (!root) root = document;
    root.querySelectorAll('.bulk-select-checkbox').forEach(function(cb) {
      cb.addEventListener('change', function(e) {
        var el = e.currentTarget;
        var beatmapId = el.getAttribute('data-beatmap-id');
        var beatmapsetId = el.getAttribute('data-beatmapset-id');
        // Try to fetch a human-friendly title from the card
        var title = null;
        try {
          var wrapper = el.closest('.beatmap-card-wrapper');
          var titleEl = wrapper ? wrapper.querySelector('.title') : null;
          title = titleEl ? titleEl.textContent.trim() : null;
        } catch(err) { /* no-op */ }
        if (el.checked) {
          if (bulkState.selected.size >= MAX_SELECTED) {
            el.checked = false;
            alert('You can select up to ' + MAX_SELECTED + ' maps.');
            return;
          }
          bulk_select(beatmapId, beatmapsetId, title);
        } else {
          bulk_deselect(beatmapId);
        }
      });
    });
    // After binding, ensure checked state reflects stored selection
    bulk_syncCheckboxesFromState();
  }

  function bulk_syncCheckboxesFromState() {
    try {
      document.querySelectorAll('.bulk-select-checkbox').forEach(function(cb) {
        var id = cb.getAttribute('data-beatmap-id');
        cb.checked = bulkState.selected.has(String(id));
      });
    } catch (err) { /* no-op */ }
  }

  function bulk_directAll() {
    var items = Array.from(bulkState.selected.values());
    if (items.length === 0) return;
    var delay = 0;
    var stepMs = BULK_DIRECT_DELAY_MS;
    items.forEach(function(item) {
      setTimeout(function() {
        var url = 'osu://b/' + item.beatmapId;
        window.location.assign(url);
      }, delay);
      delay += stepMs;
    });
  }

  function bulk_initPanelButtons() {
    var directBtn = document.getElementById('bulkDirectAllBtn');
    if (directBtn) directBtn.addEventListener('click', bulk_directAll);

    var selectAllBtn = document.getElementById('bulkSelectAllBtn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', async function() {
        // Toggle to clear if anything is selected
        if (bulkState.selected.size > 0) {
          bulk_clearAll();
          return;
        }
        // Otherwise, select from current page onward up to MAX_SELECTED
        var btn = bulk_getSelectAllBtn();
        if (btn) { btn.disabled = true; btn.textContent = 'Selecting...'; }
        await bulk_selectAllAcrossPages();
        if (btn) { btn.disabled = false; bulk_updateSelectAllButton(); }
      });
    }
  }

  // Initialize after page load
  document.addEventListener('DOMContentLoaded', function() {
    bulk_initPanelButtons();
    bulk_restoreFromStorage();
    bulk_initCheckboxSync(document);
  });
})();

