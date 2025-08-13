// Profile page chart
(function(){
  function initProfilePie(tagLabels, tagData) {
    var canvas = document.getElementById('tagsChart');
    if (!canvas || !tagLabels || !tagData) return;
    new Chart(canvas.getContext('2d'), {
      type: 'pie',
      data: { labels: tagLabels, datasets: [{ label: 'Most Used Tags', data: tagData, backgroundColor: [
        'rgba(255, 99, 132, 0.2)', 'rgba(54, 162, 235, 0.2)', 'rgba(255, 206, 86, 0.2)',
        'rgba(75, 192, 192, 0.2)', 'rgba(153, 102, 255, 0.2)', 'rgba(255, 159, 64, 0.2)'
      ], borderColor: [
        'rgba(255, 99, 132, 1)', 'rgba(54, 162, 235, 1)', 'rgba(255, 206, 86, 1)',
        'rgba(75, 192, 192, 1)', 'rgba(153, 102, 255, 1)', 'rgba(255, 159, 64, 1)'
      ], borderWidth: 1 }] },
      options: { responsive: true, legend: { position: 'top' }, animation: { animateScale: true, animateRotate: true } }
    });
  }
  window.initProfile = function(cfg) { initProfilePie(cfg.tagLabels, cfg.tagData); }
})();

