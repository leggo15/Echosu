(function () {
  function $(sel) { return document.querySelector(sel); }
  function createSvgEl(tag, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  function drawGraph(canvas, ts, state) {
    if (!canvas || !ts || !Array.isArray(ts.times_s)) return;

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var width = canvas.clientWidth * dpr;
    var height = canvas.clientHeight * dpr;
    if (!width) { width = 800; }
    if (!height) { height = 280; }

    var sizeChanged = (canvas.width !== width || canvas.height !== height);
    if (sizeChanged) {
      canvas.width = width; canvas.height = height;
      state.needFullRedraw = true;
    }

    // Prepare cached static canvas
    if (state.needFullRedraw || !state.staticCanvas) {
      var oc = document.createElement('canvas');
      oc.width = width; oc.height = height;
      var octx = oc.getContext('2d');

      var padding = { left: 54, right: 70, top: 24, bottom: 34 };
      var plotW = width - padding.left - padding.right;
      var plotH = height - padding.top - padding.bottom;

      var times = ts.times_s;
      var aim = ts.aim || [];
      var speed = ts.speed || [];
      var total = ts.total || [];
      var n = Math.min(times.length, aim.length, speed.length, total.length);
      if (n === 0) {
        octx.fillStyle = '#111';
        octx.fillRect(0, 0, width, height);
        octx.fillStyle = '#aaa';
        octx.font = (12 * dpr) + 'px sans-serif';
        octx.fillText('No difficulty timeline available', padding.left, padding.top + 20);
        state.staticCanvas = oc;
        // Provide plot metrics even if minimal
        if (typeof window.__SET_ROSU_PLOT__ === 'function') {
          window.__SET_ROSU_PLOT__({ padding: padding, plotW: plotW, plotH: plotH, minX: 0, maxX: 1, clockRate: 1 });
        }
        state.needFullRedraw = false;
        // Blit and return
        ctx.drawImage(state.staticCanvas, 0, 0);
        return;
      }

      times = times.slice(0, n);
      aim = aim.slice(0, n);
      speed = speed.slice(0, n);
      total = total.slice(0, n);

      // Shift bin center times by first object time so X=0 aligns with audio timeline
      var t0 = (typeof ts.t0_s === 'number') ? ts.t0_s : 0;
      var timesAbs = new Array(n);
      for (var ti = 0; ti < n; ti++) timesAbs[ti] = times[ti] + t0;

      // Align left boundary with the actual map start (first object time)
      var firstObj = t0;
      var maxX = timesAbs[n - 1];
      var minX = firstObj;


      // Scale strains to approximate stars. Prefer modded stars from backend if present.
      var totalStarsAttr = parseFloat(canvas.getAttribute('data-total-stars') || '0');
      if (typeof ts.stars === 'number' && ts.stars > 0) {
        totalStarsAttr = ts.stars;
      }
      var scale = 1;
      if (totalStarsAttr > 0) {
        // use 95th percentile of total to avoid outliers
        var tmp = total.slice().sort(function(a, b){ return a - b; });
        var idx = Math.max(0, Math.min(tmp.length - 1, Math.floor(tmp.length * 0.95)));
        var p95 = tmp[idx] || 1;
        scale = totalStarsAttr / p95;
      }

      // Apply scaling and compute maxY on scaled values
      var aimS = new Array(n);
      var speedS = new Array(n);
      var totalS = new Array(n);
      var maxY = 0;
      for (var i = 0; i < n; i++) {
        var a = aim[i] * scale;
        var s = speed[i] * scale;
        var t = total[i] * scale;
        aimS[i] = a; speedS[i] = s; totalS[i] = t;
        if (a > maxY) maxY = a;
        if (s > maxY) maxY = s;
        if (t > maxY) maxY = t;
      }
      if (maxY <= 0) maxY = 1;

      function xScale(x) {
        return padding.left + ((x - minX) / (maxX - minX || 1)) * plotW;
      }
      function yScale(y) {
        return padding.top + plotH - (y / maxY) * plotH;
      }

      // background
      octx.fillStyle = '#111';
      octx.fillRect(0, 0, width, height);

    // grid + ticks
    var gridLines = 5;
      octx.strokeStyle = 'rgba(255,255,255,0.12)';
      octx.lineWidth = 1;
      octx.beginPath();
      for (var g = 0; g <= gridLines; g++) {
        var gy = padding.top + (g / gridLines) * plotH;
        octx.moveTo(padding.left, gy);
        octx.lineTo(width - padding.right, gy);
      }
      octx.stroke();

    // y-axis ticks/labels (Stars)
      octx.fillStyle = '#aaa';
      octx.font = (11 * dpr) + 'px sans-serif';
      octx.textAlign = 'right';
      octx.textBaseline = 'middle';
      for (var yT = 0; yT <= gridLines; yT++) {
        var val = (maxY * (yT / gridLines));
        var y = padding.top + plotH - (yT / gridLines) * plotH;
        octx.fillText(val.toFixed(2), padding.left - 6, y);
      }

    // x-axis ticks/labels (time)
      function formatTime(seconds) {
      seconds = Math.max(0, Math.round(seconds));
      var hrs = Math.floor(seconds / 3600);
      var mins = Math.floor((seconds % 3600) / 60);
      var secs = seconds % 60;
      function pad(n) { return n < 10 ? '0' + n : '' + n; }
      var out = pad(mins) + ':' + pad(secs);
      if (hrs > 0) { out = hrs + ':' + pad(mins) + ':' + pad(secs); }
      return out;
      }

      octx.textAlign = 'center';
      octx.textBaseline = 'top';
      var approxXTicks = Math.max(4, Math.floor(plotW / (90 * dpr)));
      var step = Math.max(1, Math.round(n / approxXTicks));
      for (var xi = 0; xi < n; xi += step) {
        var x = xScale(timesAbs[xi]);
        octx.fillText(formatTime(timesAbs[xi]), x, height - padding.bottom + 6);
      }

      function drawSeries(data, color, widthPx) {
        octx.strokeStyle = color;
        octx.lineWidth = widthPx * dpr;
        octx.beginPath();
        for (var i = 0; i < n; i++) {
          var x = xScale(timesAbs[i]);
          var y = yScale(data[i]);
          if (i === 0) octx.moveTo(x, y);
          else octx.lineTo(x, y);
        }
        octx.stroke();
      }

    // fill under total
      octx.fillStyle = 'rgba(0, 153, 255, 0.15)';
      octx.beginPath();
      for (var i = 0; i < n; i++) {
        var x = xScale(timesAbs[i]);
        var y = yScale(totalS[i]);
        if (i === 0) octx.moveTo(x, y);
        else octx.lineTo(x, y);
      }
      octx.lineTo(xScale(timesAbs[n - 1]), yScale(0));
      octx.lineTo(xScale(timesAbs[0]), yScale(0));
      octx.closePath();
      octx.fill();

      drawSeries(aimS, '#ff4d6a', 1.5);
      drawSeries(speedS, '#ffb000', 1.5);
      drawSeries(totalS, '#00a8ff', 2.0);

    // Provide plotting metrics to tags overlay renderer
      if (typeof window.__SET_ROSU_PLOT__ === 'function') {
        var cr = (typeof ts.clock_rate === 'number' && ts.clock_rate > 0) ? ts.clock_rate : 1;
        window.__SET_ROSU_PLOT__({
          padding: padding,
          plotW: plotW,
          plotH: plotH,
          minX: minX,
          maxX: maxX,
          clockRate: cr,
        });
      }
      // Cache static canvas and data needed for hover calculations
      state.staticCanvas = oc;
      state.needFullRedraw = false;
      state._cache = {
        padding: padding,
        plotW: plotW,
        plotH: plotH,
        minX: minX,
        maxX: maxX,
        timesAbs: timesAbs,
        n: n,
        aimS: aimS,
        speedS: speedS,
        totalS: totalS
      };
    }

    // Draw static layer
    ctx.drawImage(state.staticCanvas, 0, 0);

    // legend top-right (static)
    (function drawLegend() {
      var items = [
        { label: 'Aim', color: '#ff4d6a' },
      { label: 'Speed', color: '#ffb000' },
      { label: 'Total', color: '#00a8ff' }
      ];
      var octx = state.staticCanvas.getContext('2d');
      var padding = state._cache.padding;
      octx.font = (11 * dpr) + 'px sans-serif';
      var legendPad = 8 * dpr;
      var rowGap = 4 * dpr;
      var sw = 14 * dpr;
      var sh = 4 * dpr;
      var maxLabelW = 0;
      octx.textAlign = 'left';
      octx.textBaseline = 'middle';
      items.forEach(function (it) { maxLabelW = Math.max(maxLabelW, octx.measureText(it.label).width); });
      var rowH = 16 * dpr;
      var boxW = legendPad * 2 + sw + 6 * dpr + maxLabelW;
      var boxH = legendPad * 2 + items.length * rowH + (items.length - 1) * rowGap;
      var boxX = state.staticCanvas.width - padding.right - boxW;
      var boxY = padding.top + 8 * dpr;
      octx.fillStyle = 'rgba(0,0,0,0.35)';
      octx.fillRect(boxX, boxY, boxW, boxH);
      for (var li = 0; li < items.length; li++) {
        var it = items[li];
        var cx = boxX + legendPad;
        var cy = boxY + legendPad + li * (rowH + rowGap) + rowH / 2;
        octx.fillStyle = it.color;
        octx.fillRect(cx, cy - sh / 2, sw, sh);
        octx.fillStyle = '#eee';
        octx.fillText(it.label, cx + sw + 6 * dpr, cy);
      }
    })();

    // hover crosshair + tooltip (dynamic only)
    if (state && state.hoverX != null && state._cache) {
      var padding = state._cache.padding;
      var plotW = state._cache.plotW;
      var minX = state._cache.minX, maxX = state._cache.maxX;
      var timesAbs = state._cache.timesAbs;
      var aimS = state._cache.aimS, speedS = state._cache.speedS, totalS = state._cache.totalS;
      var n = state._cache.n;
      function xScale(x) { return padding.left + ((x - minX) / (maxX - minX || 1)) * plotW; }
      function formatTime(seconds) {
        seconds = Math.max(0, Math.round(seconds));
        var hrs = Math.floor(seconds / 3600);
        var mins = Math.floor((seconds % 3600) / 60);
        var secs = seconds % 60;
        function pad(n) { return n < 10 ? '0' + n : '' + n; }
        var out = pad(mins) + ':' + pad(secs);
        if (hrs > 0) { out = hrs + ':' + pad(mins) + ':' + pad(secs); }
        return out;
      }
      var hx = Math.max(padding.left, Math.min(width - padding.right, state.hoverX));
      var xVal = minX + ((hx - padding.left) / plotW) * (maxX - minX);
      // Binary search for nearest index (timesAbs is sorted)
      var lo = 0, hi = n - 1;
      while (lo < hi) {
        var mid = (lo + hi) >> 1;
        if (timesAbs[mid] < xVal) lo = mid + 1; else hi = mid;
      }
      var nearest = lo;
      if (nearest > 0 && Math.abs(timesAbs[nearest - 1] - xVal) < Math.abs(timesAbs[nearest] - xVal)) nearest = nearest - 1;
      var cx = xScale(timesAbs[nearest]);
      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.beginPath();
      ctx.moveTo(cx, state._cache.padding.top);
      ctx.lineTo(cx, height - state._cache.padding.bottom);
      ctx.stroke();
      var tipPad = 6 * dpr;
      var tipText = formatTime(timesAbs[nearest]) +
                    '\nAim=' + aimS[nearest].toFixed(2) + '★' +
                    '\nSpeed=' + speedS[nearest].toFixed(2) + '★' +
                    '\nTotal=' + totalS[nearest].toFixed(2) + '★';
      var lines = tipText.split('\n');
      ctx.font = (11 * dpr) + 'px sans-serif';
      var tw = 0;
      for (var i = 0; i < lines.length; i++) { var w = ctx.measureText(lines[i]).width; if (w > tw) tw = w; }
      var th = lines.length * (14 * dpr);
      var bx = Math.min(cx + 10 * dpr, width - state._cache.padding.right - (tw + tipPad * 2));
      var by = state._cache.padding.top + 10 * dpr;
      ctx.fillStyle = 'rgba(0,0,0,0.7)';
      ctx.fillRect(bx, by, tw + tipPad * 2, th + tipPad * 2);
      ctx.fillStyle = '#fff';
      for (var li = 0; li < lines.length; li++) {
        ctx.fillText(lines[li], bx + tipPad, by + tipPad + (li + 0.8) * (14 * dpr));
      }
    }

    // Draw tag overlay if available
    if (typeof window.__ROSU_OVERLAY__ === 'function' && state._cache) {
      try {
        // Save context state before drawing overlay
        ctx.save();
        window.__ROSU_OVERLAY__(state);
        ctx.restore();
      } catch (e) {
        console.warn('Error drawing tag overlay:', e);
        ctx.restore(); // Ensure context is restored even on error
      }
    }
  }

  function init() {
    var canvas = document.getElementById('rosuGraphCanvas');
    if (!canvas) return;
    var baseUrl = canvas.getAttribute('data-ts-url');
    if (!baseUrl) return;
    // Build query URL with current mods from UI if present
    function currentModsString() {
      var wrap = canvas.closest('.rosu-graph-card');
      if (!wrap) return '';
      var btns = wrap.querySelectorAll('.mod-toggle.active');
      var mods = [];
      btns.forEach(function(b){ mods.push(b.getAttribute('data-mod')); });
      // Ensure mutual exclusion: DT/HT and HR/EZ (server also enforces)
      var set = new Set(mods);
      if (set.has('DT') && set.has('HT')) { set.delete('HT'); }
      if (set.has('HR') && set.has('EZ')) { set.delete('EZ'); }
      return Array.from(set).join('');
    }

    function buildUrl() {
      var mods = currentModsString();
      var u = baseUrl;
      var qp = [];
      var windowS = canvas.getAttribute('data-window-s') || '1';
      if (windowS) qp.push('window_s=' + encodeURIComponent(windowS));
      if (mods) qp.push('mods=' + encodeURIComponent(mods));
      if (qp.length) u += (u.indexOf('?') === -1 ? '?' : '&') + qp.join('&');
      return u;
    }

    function fetchAndDraw() {
      var url = buildUrl();
      fetch(url, { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (ts) {
        if (!ts) {
          // draw empty state
          var ctx = canvas.getContext('2d');
          var dpr = window.devicePixelRatio || 1;
          var width = canvas.clientWidth * dpr || 800;
          var height = canvas.clientHeight * dpr || 280;
          canvas.width = width; canvas.height = height;
          ctx.fillStyle = '#111';
          ctx.fillRect(0, 0, width, height);
          ctx.fillStyle = '#aaa';
          ctx.font = (12 * dpr) + 'px sans-serif';
          ctx.fillText('No difficulty timeline available', 12, 24);
          return;
        }
        var state = { hoverX: null, needFullRedraw: true, staticCanvas: null, _cache: null };
        drawGraph(canvas, ts, state);
        window.__ROSUREFRESH__ = function () { drawGraph(canvas, ts, state); };
        var resizeRaf = null;
        window.addEventListener('resize', function () {
          if (resizeRaf) cancelAnimationFrame(resizeRaf);
          resizeRaf = requestAnimationFrame(function () { drawGraph(canvas, ts, state); });
        });
        canvas.addEventListener('mousemove', function (e) {
          var rect = canvas.getBoundingClientRect();
          var dpr = window.devicePixelRatio || 1;
          state.hoverX = (e.clientX - rect.left) * dpr;
          // Only redraw dynamic overlay: copy static and draw hover components
          drawGraph(canvas, ts, state);
        });
        canvas.addEventListener('mouseleave', function () {
          state.hoverX = null;
          drawGraph(canvas, ts, state);
        });
      })
      .catch(function () { /* silent */ });
    }

    fetchAndDraw();

    // Wire up mod toggle buttons if present
    var container = canvas.closest('.rosu-graph-card');
    if (container) {
      container.addEventListener('click', function(e){
        var t = e.target;
        if (!t.classList || !t.classList.contains('mod-toggle')) return;
        var mod = t.getAttribute('data-mod');
        // Toggle active state; enforce exclusivity rules visually
        var active = t.classList.toggle('active');
        if (mod === 'DT' && active) {
          var ht = container.querySelector('.mod-toggle[data-mod="HT"]');
          if (ht) ht.classList.remove('active');
        }
        if (mod === 'HT' && active) {
          var dt = container.querySelector('.mod-toggle[data-mod="DT"]');
          if (dt) dt.classList.remove('active');
        }
        if (mod === 'HR' && active) {
          var ez = container.querySelector('.mod-toggle[data-mod="EZ"]');
          if (ez) ez.classList.remove('active');
        }
        if (mod === 'EZ' && active) {
          var hr = container.querySelector('.mod-toggle[data-mod="HR"]');
          if (hr) hr.classList.remove('active');
        }
        // Refetch graph with new mods
        fetchAndDraw();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();


