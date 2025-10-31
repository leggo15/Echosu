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

      var buttons = document.querySelectorAll('.tab-button');
      buttons.forEach(function(btn){
        btn.addEventListener('click', function(){
          var target = btn.getAttribute('data-tab') || 'latest';
          setActiveTab(target);
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


