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


