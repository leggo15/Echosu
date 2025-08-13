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
    canvas.width = width; canvas.height = height;

    var padding = { left: 54, right: 70, top: 24, bottom: 34 };
    var plotW = width - padding.left - padding.right;
    var plotH = height - padding.top - padding.bottom;

    var times = ts.times_s;
    var aim = ts.aim || [];
    var speed = ts.speed || [];
    var total = ts.total || [];
    var n = Math.min(times.length, aim.length, speed.length, total.length);
    if (n === 0) {
      ctx.fillStyle = '#aaa';
      ctx.font = (12 * dpr) + 'px sans-serif';
      ctx.fillText('No difficulty timeline available', padding.left, padding.top + 20);
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
     // Clamp maxX using precise end from timeseries or known total length
     if (typeof ts.t_end_s === 'number' && ts.t_end_s > 0) {
       maxX = Math.min(maxX, ts.t_end_s);
     }
     var totalLen = parseFloat(canvas.getAttribute('data-total-length') || '0');
     if (!isNaN(totalLen) && totalLen > 0) {
       maxX = Math.min(maxX, totalLen);
     }
     var minX = firstObj;


    // Scale strains to approximate stars using map's overall star rating.
    var totalStarsAttr = parseFloat(canvas.getAttribute('data-total-stars') || '0');
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
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, width, height);

    // grid + ticks
    var gridLines = 5;
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var g = 0; g <= gridLines; g++) {
      var gy = padding.top + (g / gridLines) * plotH;
      ctx.moveTo(padding.left, gy);
      ctx.lineTo(width - padding.right, gy);
    }
    ctx.stroke();

    // y-axis ticks/labels (Stars)
    ctx.fillStyle = '#aaa';
    ctx.font = (11 * dpr) + 'px sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (var yT = 0; yT <= gridLines; yT++) {
      var val = (maxY * (yT / gridLines));
      var y = padding.top + plotH - (yT / gridLines) * plotH;
      ctx.fillText(val.toFixed(2), padding.left - 6, y);
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

    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    var approxXTicks = Math.max(4, Math.floor(plotW / (90 * dpr)));
    var step = Math.max(1, Math.round(n / approxXTicks));
    for (var xi = 0; xi < n; xi += step) {
      var x = xScale(timesAbs[xi]);
      ctx.fillText(formatTime(timesAbs[xi]), x, height - padding.bottom + 6);
    }

    function drawSeries(data, color, widthPx) {
      ctx.strokeStyle = color;
      ctx.lineWidth = widthPx * dpr;
      ctx.beginPath();
      for (var i = 0; i < n; i++) {
        var x = xScale(timesAbs[i]);
        var y = yScale(data[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // fill under total
    ctx.fillStyle = 'rgba(0, 153, 255, 0.15)';
    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      var x = xScale(timesAbs[i]);
      var y = yScale(totalS[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.lineTo(xScale(timesAbs[n - 1]), yScale(0));
    ctx.lineTo(xScale(timesAbs[0]), yScale(0));
    ctx.closePath();
    ctx.fill();

    drawSeries(aimS, '#ff4d6a', 1.5);
    drawSeries(speedS, '#ffb000', 1.5);
    drawSeries(totalS, '#00a8ff', 2.0);

    // Provide plotting metrics to tags overlay renderer
    if (typeof window.__SET_ROSU_PLOT__ === 'function') {
      window.__SET_ROSU_PLOT__({
        padding: padding,
        plotW: plotW,
        plotH: plotH,
        minX: minX,
        maxX: maxX,
      });
    }

    // legend top-right
    var items = [
      { label: 'Aim', color: '#ff4d6a' },
      { label: 'Speed', color: '#ffb000' },
      { label: 'Total', color: '#00a8ff' }
    ];
    ctx.font = (11 * dpr) + 'px sans-serif';
    var legendPad = 8 * dpr;
    var rowGap = 4 * dpr;
    var sw = 14 * dpr;
    var sh = 4 * dpr;
    var maxLabelW = 0;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    items.forEach(function (it) { maxLabelW = Math.max(maxLabelW, ctx.measureText(it.label).width); });
    var rowH = 16 * dpr;
    var boxW = legendPad * 2 + sw + 6 * dpr + maxLabelW;
    var boxH = legendPad * 2 + items.length * rowH + (items.length - 1) * rowGap;
    var boxX = width - padding.right - boxW;
    var boxY = padding.top + 8 * dpr;
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fillRect(boxX, boxY, boxW, boxH);
    for (var li = 0; li < items.length; li++) {
      var it = items[li];
      var cx = boxX + legendPad;
      var cy = boxY + legendPad + li * (rowH + rowGap) + rowH / 2;
      ctx.fillStyle = it.color;
      ctx.fillRect(cx, cy - sh / 2, sw, sh);
      ctx.fillStyle = '#eee';
      ctx.fillText(it.label, cx + sw + 6 * dpr, cy);
    }

    // hover crosshair + tooltip
    if (state && state.hoverX != null) {
      var hx = Math.max(padding.left, Math.min(width - padding.right, state.hoverX));
      // find nearest index
      var xVal = minX + ((hx - padding.left) / plotW) * (maxX - minX);
      var nearest = 0, best = Infinity;
      for (var k = 0; k < n; k++) {
        var diff = Math.abs(timesAbs[k] - xVal);
        if (diff < best) { best = diff; nearest = k; }
      }
      var cx = xScale(timesAbs[nearest]);
      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.beginPath();
      ctx.moveTo(cx, padding.top);
      ctx.lineTo(cx, height - padding.bottom);
      ctx.stroke();

      // tooltip box
      var tipPad = 6 * dpr;
      var tipText = formatTime(timesAbs[nearest]) +
                    '\nAim=' + aimS[nearest].toFixed(2) + '★' +
                    '\nSpeed=' + speedS[nearest].toFixed(2) + '★' +
                    '\nTotal=' + totalS[nearest].toFixed(2) + '★';
      var lines = tipText.split('\n');
      ctx.font = (11 * dpr) + 'px sans-serif';
      var tw = 0;
      lines.forEach(function (ln) { tw = Math.max(tw, ctx.measureText(ln).width); });
      var th = lines.length * (14 * dpr);
      var bx = Math.min(cx + 10 * dpr, width - padding.right - (tw + tipPad * 2));
      var by = padding.top + 10 * dpr;
      ctx.fillStyle = 'rgba(0,0,0,0.7)';
      ctx.fillRect(bx, by, tw + tipPad * 2, th + tipPad * 2);
      ctx.fillStyle = '#fff';
      for (var li = 0; li < lines.length; li++) {
        ctx.fillText(lines[li], bx + tipPad, by + tipPad + (li + 0.8) * (14 * dpr));
      }
    }
  }

  function init() {
    var canvas = document.getElementById('rosuGraphCanvas');
    if (!canvas) return;
    var url = canvas.getAttribute('data-ts-url');
    if (!url) return;

    fetch(url, { credentials: 'same-origin' })
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
        var state = { hoverX: null };
        drawGraph(canvas, ts, state);
        window.__ROSUREFRESH__ = function () { drawGraph(canvas, ts, state); };
        window.addEventListener('resize', function () { drawGraph(canvas, ts, state); });
        canvas.addEventListener('mousemove', function (e) {
          var rect = canvas.getBoundingClientRect();
          var dpr = window.devicePixelRatio || 1;
          state.hoverX = (e.clientX - rect.left) * dpr;
          drawGraph(canvas, ts, state);
        });
        canvas.addEventListener('mouseleave', function () {
          state.hoverX = null;
          drawGraph(canvas, ts, state);
        });
      })
      .catch(function () { /* silent */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();


