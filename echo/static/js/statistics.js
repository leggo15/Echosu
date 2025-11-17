(function(){
  function buildBarChart(canvasId, labels, data, onClickBar) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !labels || !labels.length) return null;
    var chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Tag Count',
          data: data,
          backgroundColor: 'rgba(54, 162, 235, 0.5)',
          borderColor: 'rgba(54, 162, 235, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        onClick: function(evt, elements) {
          if (!elements || !elements.length) return;
          var first = elements[0];
          var idx = first.index;
          if (typeof onClickBar === 'function') onClickBar(idx);
        }
      }
    });
    return chart;
  }

  function openSearchWithQuery(query) {
    if (!query) return;
    var url = new URL(window.location.origin + '/search_results/');
    url.searchParams.set('query', query);
    window.location.href = url.toString();
  }

  function refreshPlayerSection(userValue, sourceValue) {
    var url = new URL(window.location.origin + '/statistics/player-data/');
    url.searchParams.set('user', userValue || '');
    url.searchParams.set('source', sourceValue || 'top');
    return fetch(url.toString(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(r){ return r.json(); })
      .catch(function(){ return { labels: [], counts: [], most_related_html: '<p>No data.</p>' }; });
  }

  window.initStatistics = function(cfg){
    cfg = cfg || {};
    var mapper = cfg.mapper || { labels: [], data: [], clickQueries: [] };
    var player = cfg.player || { labels: [], data: [] };

    // Mapper chart with clickable bars -> search_results
    buildBarChart('mapperChart', mapper.labels, mapper.data, function(i){
      var q = (mapper.clickQueries && mapper.clickQueries[i]) || '';
      openSearchWithQuery(q);
    });

    // Player chart (no click -> just a plain chart)
    var playerChart = buildBarChart('playerChart', player.labels, player.data, null);

    // Toggle handling: auto reload on change
    var select = document.getElementById('playerSource');
    if (select) {
      select.addEventListener('change', function(){
        var userInput = document.querySelector('.stats-form input[name="user"]');
        var userValue = userInput ? userInput.value : '';
        var sourceValue = select.value;
        refreshPlayerSection(userValue, sourceValue).then(function(payload){
          // Update chart data
          if (playerChart) {
            playerChart.data.labels = payload.labels || [];
            playerChart.data.datasets[0].data = payload.counts || [];
            playerChart.update();
          }
          // Update Most Related card
          var container = document.getElementById('mostRelatedContainer');
          if (container) {
            container.innerHTML = payload.most_related_html || '<p>No data.</p>';
            // Initialize audio on newly injected card(s)
            if (window.initAudioDefaults) {
              window.initAudioDefaults(container);
            }
            // Initialize tagging behaviors so login state and tag list render correctly
            if (window.initTaggingFor) {
              window.initTaggingFor(container);
            }
          }
        });
      });
    }
    // Ensure audio defaults for initial cards as well
    if (window.initAudioDefaults) { window.initAudioDefaults(document); }
    if (window.initTaggingFor) { window.initTaggingFor(document); }
  };
})();


// Tabs logic for Statistics page (Latest Maps default, lazy-init charts on User tab)
(function(){
  var chartsInitialized = false;
  var myChartsInitialized = false;
  var globalChartsInitialized = false;
  var latestPollTimer = null;
  var latestPollBusy = false;
  var adminChartsInitialized = false;
  var adminLatestTimer = null;
  var adminLatestBusy = false;
  var adminHourlyTimer = null;
  var adminCharts = { searches: null, uniques: null };
  var adminDataCache = null;
  var adminTagCache = null;

  function startLatestPoll() {
    if (latestPollTimer) return;
    function tick(){
      if (latestPollBusy) return;
      latestPollBusy = true;
      try {
        var sec = document.querySelector('.tab-section.is-active');
        if (!sec || sec.getAttribute('data-section') !== 'latest') return;
        fetch('/statistics/latest-maps/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function(r){ return r.json(); })
          .then(function(payload){
            if (!payload || !payload.html) return;
            var list = document.getElementById('latestMapsList');
            if (!list) return;
            if (window.TagManager && typeof window.TagManager.clearTagCache === 'function') { try { window.TagManager.clearTagCache(); } catch(e) {} }
            // Preserve heading
            var head = list.querySelector('h2');
            list.innerHTML = '';
            if (head) { list.appendChild(head); }
            var wrapper = document.createElement('div');
            wrapper.innerHTML = payload.html;
            while (wrapper.firstChild) { list.appendChild(wrapper.firstChild); }
            if (window.initAudioDefaults) { window.initAudioDefaults(list); }
            if (window.initTaggingFor) { window.initTaggingFor(list); }
          })
          .finally(function(){ latestPollBusy = false; });
      } catch (e) { latestPollBusy = false; }
    }
    // Start after a short delay to avoid racing initial page render
    latestPollTimer = setInterval(function(){ if (!document.hidden) tick(); }, 30000);
  }

  function stopLatestPoll() {
    if (latestPollTimer) { clearInterval(latestPollTimer); latestPollTimer = null; }
  }

  function startAdminLatestPoll() {
    if (adminLatestTimer) return;
    function tick(){
      if (adminLatestBusy) return;
      adminLatestBusy = true;
      try {
        var sec = document.querySelector('.tab-section.is-active');
        if (!sec || sec.getAttribute('data-section') !== 'admin') return;
        fetch('/statistics/latest-searches/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function(r){ return r.json(); })
          .then(function(payload){
            if (!payload || !payload.html) return;
            var div = document.getElementById('adminLatestSearches');
            if (!div) return;
            div.innerHTML = payload.html;
          })
          .finally(function(){ adminLatestBusy = false; });

        // Button events log (independent; do not gate busy flag on this)
        fetch('/statistics/latest-clicks/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function(r){ return r.json(); })
          .then(function(payload){
            if (!payload || !payload.html) return;
            var div2 = document.getElementById('adminLatestClicks');
            if (!div2) return;
            div2.innerHTML = payload.html;
          })
          .catch(function(){ /* ignore */ });
      } catch (e) { adminLatestBusy = false; }
    }
    adminLatestTimer = setInterval(function(){ if (!document.hidden) tick(); }, 30000);
    // Initial tick
    setTimeout(function(){ if (!document.hidden) tick(); }, 100);
  }

  function stopAdminLatestPoll() {
    if (adminLatestTimer) { clearInterval(adminLatestTimer); adminLatestTimer = null; }
  }

  function fetchAdminData(){
    return fetch('/statistics/admin-data/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(r){ return r.json(); })
      .catch(function(){ return null; });
  }

  function renderBar(canvasId, labels, data, label, color){
    var canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    var ctx = canvas.getContext('2d');
    return new Chart(ctx, {
      type: 'bar',
      data: { labels: labels, datasets: [{ label: label || '', data: data || [], backgroundColor: color || 'rgba(99, 132, 255, 0.5)', borderColor: color ? color.replace('0.5','1') : 'rgba(99, 132, 255, 1)', borderWidth: 1 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
    });
  }

  function updateAdminCharts(){
    if (!adminDataCache) return;
    try {
      var periodSearch = (document.getElementById('adminSearchPeriod') || {}).value || 'hour';
      var periodUniques = (document.getElementById('adminUniquesPeriod') || {}).value || 'hour';
      var s = (adminDataCache.searches && adminDataCache.searches[periodSearch]) || { labels: [], counts: [] };
      var u = (adminDataCache.uniques && adminDataCache.uniques[periodUniques]) || { labels: [], counts: [] };
      if (!adminCharts.searches) {
        adminCharts.searches = renderBar('adminSearchesChart', s.labels, s.counts, 'Searches', 'rgba(54, 162, 235, 0.5)');
      } else {
        adminCharts.searches.data.labels = s.labels || [];
        adminCharts.searches.data.datasets[0].data = s.counts || [];
        adminCharts.searches.update();
      }
      if (!adminCharts.uniques) {
        adminCharts.uniques = renderBar('adminUniquesChart', u.labels, u.counts, 'Unique users', 'rgba(255, 159, 64, 0.5)');
      } else {
        adminCharts.uniques.data.labels = u.labels || [];
        adminCharts.uniques.data.datasets[0].data = u.counts || [];
        adminCharts.uniques.update();
      }
      // Per-button tiles: last used + total uses in last 30 days
      var container = document.getElementById('adminAvgClicksOverview');
      if (container) {
        container.innerHTML = '';
        var counts = adminDataCache.click_counts_30d || {};
        var lastUsed = adminDataCache.last_used_per_action || {};
        var keysMap = {};
        Object.keys(counts || {}).forEach(function(k){ keysMap[k] = true; });
        Object.keys(lastUsed || {}).forEach(function(k){ keysMap[k] = true; });
        var actions = Object.keys(keysMap).sort();
        if (!actions.length) {
          var empty = document.createElement('p');
          empty.textContent = 'No data.';
          container.appendChild(empty);
        } else {
          actions.forEach(function(a){
            var total = counts[a] || 0;
            var raw = lastUsed[a];
            var display = '-';
            if (raw) {
              try { display = new Date(raw).toLocaleDateString(); } catch (e) { display = raw; }
            }
            var tile = document.createElement('div');
            tile.className = 'stat-item';
            tile.innerHTML =
              '<span class="label">' + a + '</span>' +
              '<span class="value">' +
                '<span class="usage-count">' + total + '</span>' +
                '<span class="usage-date" style="margin-left:8px; font-size:0.8em; opacity:0.75;">' + display + '</span>' +
              '</span>';
            container.appendChild(tile);
          });
        }
      }

      // Top 25 searched tags
      var topTagsContainer = document.getElementById('adminTopTags');
      if (topTagsContainer) {
        topTagsContainer.innerHTML = '';
        var topTags = adminDataCache.top_tags || [];
        if (!topTags.length) {
          var msg = document.createElement('p');
          msg.textContent = 'No data.';
          topTagsContainer.appendChild(msg);
        } else {
          topTags.forEach(function(row){
            var tile = document.createElement('div');
            tile.className = 'stat-item';
            var modeLabel = row.mode ? (' (' + row.mode.toUpperCase() + ')') : '';
            tile.innerHTML = '<span class="label">' + row.name + modeLabel + '</span><span class="value">' + row.count + '</span>';
            topTagsContainer.appendChild(tile);
          });
        }
      }
    } catch (e) {}
  }

  function fetchAdminTagData(tag, mode){
    var url = new URL(window.location.origin + '/statistics/admin-tag/');
    url.searchParams.set('tag', tag || '');
    if (mode) { url.searchParams.set('mode', mode); }
    return fetch(url.toString(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(r){ return r.json(); })
      .catch(function(){ return null; });
  }

  var adminTagChart = null;

  function updateAdminTagView(){
    if (!adminTagCache) return;
    try {
      var period = (document.getElementById('adminTagPeriod') || {}).value || 'hour';
      var s = (adminTagCache.searches && adminTagCache.searches[period]) || { labels: [], counts: [] };
      var labels = s.labels || [];
      var data = s.counts || [];

      var canvas = document.getElementById('adminTagChart');
      if (canvas) {
        if (!adminTagChart) {
          adminTagChart = renderBar('adminTagChart', labels, data, 'Tag searches', 'rgba(153, 102, 255, 0.5)');
        } else {
          adminTagChart.data.labels = labels;
          adminTagChart.data.datasets[0].data = data;
          adminTagChart.update();
        }
      }

      var statsContainer = document.getElementById('adminTagStats');
      if (statsContainer) {
        statsContainer.innerHTML = '';
        var totals = adminTagCache.totals || {};
        var ct = adminTagCache.click_through || {};
        var tiles = [
          { label: 'Mode', value: String((adminTagCache.mode || 'std')).toUpperCase() },
          { label: 'Searches (all time)', value: totals.searches_all_time },
          { label: 'Searches (last 30d)', value: totals.searches_last_30d },
          { label: 'Avg searches/day (30d)', value: (Math.round((totals.avg_searches_per_day_30d || 0) * 100) / 100) },
          { label: 'Unique users (all time)', value: totals.unique_users_all_time },
          { label: 'Unique users (last 30d)', value: totals.unique_users_last_30d },
          { label: 'Avg unique/day (30d)', value: (Math.round((totals.avg_unique_users_per_day_30d || 0) * 100) / 100) },
          { label: 'Searches with Direct/View (all time)', value: ct.searches_with_direct_or_view_all_time },
          { label: '% with Direct/View (all time)', value: (Math.round((ct.percent_with_direct_or_view_all_time || 0) * 10) / 10) + '%' }
        ];
        var any = false;
        tiles.forEach(function(t){
          if (t.value === undefined || t.value === null) return;
          any = true;
          var tile = document.createElement('div');
          tile.className = 'stat-item';
          tile.innerHTML = '<span class="label">' + t.label + '</span><span class="value">' + t.value + '</span>';
          statsContainer.appendChild(tile);
        });
        if (!any) {
          var msg = document.createElement('p');
          msg.textContent = 'No data for this tag.';
          statsContainer.appendChild(msg);
        }
      }
    } catch (e) {}
  }

  function initAdmin(){
    if (adminChartsInitialized) return;
    adminChartsInitialized = true;
    fetchAdminData().then(function(data){
      if (!data) return;
      adminDataCache = data;
      updateAdminCharts();
    });
    // Bind period toggles
    var sp = document.getElementById('adminSearchPeriod');
    var up = document.getElementById('adminUniquesPeriod');
    if (sp) sp.addEventListener('change', updateAdminCharts);
    if (up) up.addEventListener('change', updateAdminCharts);
    // Auto-refresh charts hourly
    adminHourlyTimer = setInterval(function(){
      if (document.hidden) return;
      fetchAdminData().then(function(data){ if (data) { adminDataCache = data; updateAdminCharts(); } });
    }, 60 * 60 * 1000);
    // Start latest searches log poll
    startAdminLatestPoll();

    // Tag detail form
    var form = document.getElementById('adminTagForm');
    var modeSel = document.getElementById('adminTagMode');
    if (form) {
      form.addEventListener('submit', function(e){
        e.preventDefault();
        var input = document.getElementById('adminTagInput');
        var val = (input && input.value) ? input.value.trim() : '';
        if (!val) return;
        var modeVal = modeSel ? modeSel.value : 'std';
        fetchAdminTagData(val, modeVal).then(function(payload){
          if (!payload) return;
          adminTagCache = payload;
          if (modeSel && payload.mode) {
            try { modeSel.value = payload.mode; } catch (e) {}
          }
          updateAdminTagView();
        });
      });
    }
    var periodSel = document.getElementById('adminTagPeriod');
    if (periodSel) {
      periodSel.addEventListener('change', updateAdminTagView);
    }
  }

  function setActiveTab(tabName) {
    var buttons = document.querySelectorAll('.tab-button');
    var sections = document.querySelectorAll('.tab-section');
    buttons.forEach(function(btn){
      var isActive = (btn.getAttribute('data-tab') === tabName);
      if (isActive) { btn.classList.add('active'); } else { btn.classList.remove('active'); }
    });
    sections.forEach(function(sec){
      var isActive = (sec.getAttribute('data-section') === tabName);
      if (isActive) { 
        sec.classList.add('is-active'); 
        try { sec.style.display = 'block'; } catch (e) {}
      } else { 
        sec.classList.remove('is-active'); 
        try { sec.style.display = 'none'; } catch (e) {}
      }
    });
  }

  window.initStatisticsTabs = function(cfg){
    try {
      var root = document.querySelector('.tabs');
      var urlParams = new URLSearchParams(window.location.search);
      var initial = urlParams.get('tab') || (root && (root.getAttribute('data-default-tab') || root.dataset.defaultTab)) || 'latest';
      // Set initial state per default
      setActiveTab(initial);
      if (initial === 'latest') { startLatestPoll(); }
      if (initial === 'user' && !chartsInitialized && window.initStatistics) {
        chartsInitialized = true;
        try { window.initStatistics(cfg || {}); } catch(e) {}
      }
      if (initial === 'global' && !globalChartsInitialized) {
        globalChartsInitialized = true;
        try { initGlobalCharts(cfg && cfg.global ? cfg.global : {}); } catch (e) {}
      }
      if (initial === 'mine' && !myChartsInitialized) {
        myChartsInitialized = true;
        try { initMyCharts(cfg && cfg.mine ? cfg.mine : {}); } catch (e) {}
      }
      if (initial === 'admin' && !adminChartsInitialized) {
        try { initAdmin(); } catch (e) {}
      }

      var buttons = document.querySelectorAll('.tab-button');
      buttons.forEach(function(btn){
        btn.addEventListener('click', function(){
          var target = btn.getAttribute('data-tab') || 'latest';
          setActiveTab(target);
          if (target === 'latest') { startLatestPoll(); } else { stopLatestPoll(); }
          if (target === 'admin') { initAdmin(); startAdminLatestPoll(); } else { stopAdminLatestPoll(); }
          // Persist tab in URL without reloading
          try {
            var u = new URL(window.location.href);
            u.searchParams.set('tab', target);
            window.history.replaceState({}, '', u.toString());
          } catch (e) {}
          if (target === 'user' && !chartsInitialized && window.initStatistics) {
            chartsInitialized = true;
            try { window.initStatistics(cfg || {}); } catch(e) {}
          }
          if (target === 'mine' && !myChartsInitialized) {
            myChartsInitialized = true;
            try { initMyCharts(cfg && cfg.mine ? cfg.mine : {}); } catch (e) {}
          }
          if (target === 'global' && !globalChartsInitialized) {
            globalChartsInitialized = true;
            try { initGlobalCharts(cfg && cfg.global ? cfg.global : {}); } catch (e) {}
          }
        });
      });
    } catch (e) {}
  };
})();

// My stats charts
function initMyCharts(mineCfg) {
  try {
    var labels = (mineCfg && mineCfg.starLabels) || [];
    var data = (mineCfg && mineCfg.starCounts) || [];
    var maxY = 0;
    try { maxY = Math.max.apply(null, (data || []).map(function(v){ return Number(v) || 0; })); } catch (e) { maxY = 0; }
    var canvas = document.getElementById('myStarChart');
    if (!canvas || !labels.length) return;
    new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Star bins (0.25)',
          data: data,
          backgroundColor: 'rgba(255, 159, 64, 0.5)',
          borderColor: 'rgba(255, 159, 64, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
            suggestedMax: (maxY > 0) ? (maxY + Math.ceil(maxY * 0.1)) : undefined,
            grace: '10%'
          },
          x: { ticks: { autoSkip: true } }
        }
      }
    });
  } catch (e) {}
}

// Global charts (star distribution and overlay human vs predicted-only)
function initGlobalCharts(globalCfg) {
  try {
    var labels = (globalCfg && globalCfg.starLabels) || [];
    var data = (globalCfg && globalCfg.starCounts) || [];
    var human = (globalCfg && globalCfg.humanCounts) || [];
    var pred = (globalCfg && globalCfg.predCounts) || [];
    var c1 = document.getElementById('globalStarChart');
    if (c1 && labels.length) {
      var maxY = 0; try { maxY = Math.max.apply(null, (data || []).map(function(v){ return Number(v) || 0; })); } catch(e) {}
      new Chart(c1.getContext('2d'), {
        type: 'bar',
        data: { labels: labels, datasets: [{ label: 'Maps', data: data, backgroundColor: 'rgba(75, 192, 192, 0.5)', borderColor: 'rgba(75, 192, 192, 1)', borderWidth: 1 }] },
        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, suggestedMax: (maxY>0)?(maxY+Math.ceil(maxY*0.1)):undefined, grace: '10%' } } }
      });
    }
    var c2 = document.getElementById('globalHumanPredChart');
    if (c2 && labels.length && (human.length || pred.length)) {
      var max2 = 0; try { max2 = Math.max.apply(null, (human.concat(pred)).map(function(v){ return Number(v)||0; })); } catch(e) {}
      new Chart(c2.getContext('2d'), {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: 'Human', data: human, backgroundColor: 'rgba(54, 162, 235, 0.5)', borderColor: 'rgba(54, 162, 235, 1)', borderWidth: 1 },
            { label: 'Predicted-only', data: pred, backgroundColor: 'rgba(255, 99, 132, 0.35)', borderColor: 'rgba(255, 99, 132, 0.9)', borderWidth: 1 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, ticks: { precision: 0 }, suggestedMax: (max2>0)?(max2+Math.ceil(max2*0.1)):undefined, grace: '10%' } },
          plugins: { legend: { position: 'top' } }
        }
      });
    }
  } catch (e) {}
}


