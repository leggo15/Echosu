// Tagset map visualization (Voronoi polygons + mapper bubbles)
// - Each tagset is a region (polygon) in a seamless tessellation (no overlap/gaps).
// - Regions are positioned to keep similar tagsets close (Jaccard similarity).
// - Inside each region, we render mapper bubbles sized by map count (clipped to polygon).
// - Hover a region to see its tags (and mapper stats); tags are also shown faintly in background.

(function () {
  function $(id) { return document.getElementById(id); }

  function safeText(v) { return (v == null) ? '' : String(v); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function enc(v) { return encodeURIComponent(String(v == null ? '' : v)); }
  function quoteIfNeeded(s) {
    s = safeText(s).trim();
    if (!s) return '';
    return (/\s/.test(s) ? ('"' + s.replace(/"/g, '\\"') + '"') : s);
  }

  function createTooltip() {
    var el = document.querySelector('.tagmap-tooltip');
    if (el) return el;
    el = document.createElement('div');
    el.className = 'tagmap-tooltip';
    el.style.display = 'none';
    // IMPORTANT: when in fullscreen, only the fullscreen element subtree is visible.
    // So we must attach the tooltip inside the fullscreen element (tag map panel) to keep it visible.
    try {
      var fs = document.fullscreenElement;
      var panel = document.getElementById('tagMapPanel');
      if (fs && panel && (fs === panel || (panel.contains && panel.contains(fs)))) {
        panel.appendChild(el);
      } else if (fs && panel && (fs.contains && fs.contains(panel))) {
        panel.appendChild(el);
      } else {
        document.body.appendChild(el);
      }
    } catch (e) {
      document.body.appendChild(el);
    }
    return el;
  }

  function categoryColor(category) {
    // Match Tag.CATEGORY_* roughly
    var m = {
      mapping_genre: '#2ecc71',
      pattern_type: '#1e90ff',
      metadata: '#9b59b6',
      other: '#ff9f43'
    };
    return m[category] || '#ff9f43';
  }

  function componentColor(idx) {
    var palette = ['#ff9f43', '#1e90ff', '#2ecc71', '#e74c3c', '#9b59b6', '#f1c40f', '#e67e22', '#16a085'];
    return palette[Math.abs(idx) % palette.length];
  }

  function fetchTagMapData(params) {
    var url = new URL(window.location.origin + '/statistics/tag-map-data/');
    Object.keys(params || {}).forEach(function (k) {
      if (params[k] != null && params[k] !== '') url.searchParams.set(k, String(params[k]));
    });
    return fetch(url.toString(), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); });
  }

  function render(container, payload, statusEl) {
    if (!container) return;
    container.innerHTML = '';

    var sets = (payload && payload.sets) ? payload.sets : [];
    if (!sets.length) {
      if (statusEl) statusEl.textContent = 'No tag data available for this mode/settings.';
      return;
    }

    // "Layout zoom": instead of transforming the SVG (camera zoom),
    // we re-render at a larger pixel size and let the container scroll.
    var zoomScale = Number(window.__tagMapLayoutZoom || 1.0) || 1.0;
    zoomScale = clamp(zoomScale, 1.0, 6.0);

    // Base viewport size
    // In fullscreen (and on tall/portrait screens), using width-only can make the map too short,
    // which prevents vertical scrolling even after moderate zoom. So we ensure the base height
    // roughly fills the available container height by inflating w0 when needed.
    var w0 = container.clientWidth || 900;
    var h0 = Math.round(w0 * 9 / 16);
    try {
      if (document.fullscreenElement) {
        var ch = container.clientHeight || 0;
        if (ch > 0) {
          var wByH = Math.round(ch * 16 / 9);
          w0 = Math.max(w0, wByH);
          h0 = Math.round(w0 * 9 / 16);
        }
      } else {
        // Keep it usable on small screens
        h0 = Math.max(360, h0);
      }
    } catch (e) {
      h0 = Math.max(360, h0);
    }

    // Actual rendered SVG size (can exceed container viewport)
    var w = Math.round(w0 * zoomScale);
    var h = Math.round(h0 * zoomScale);

    // Force container height for browsers without aspect-ratio support / for consistent SVG sizing.
    // In fullscreen, CSS controls the available height; don't override it here.
    try {
      if (!document.fullscreenElement) container.style.height = String(h0) + 'px';
      else container.style.height = '';
    } catch (e) {}

    var svg = d3.select(container).append('svg')
      .attr('width', w)
      .attr('height', h)
      .attr('viewBox', '0 0 ' + w + ' ' + h)
      .style('display', 'block');

    var tooltip = createTooltip();
    var selectedMapper = window.__tagMapSelectedMapper || null;

    // Space-filling layout (treemap)
    // This gives us seamless polygons (rectangles) whose area is proportional to map_count.
    // NOTE: we intentionally do NOT use d3.zoom() here; scroll is our navigation mechanism.
    var zoomG = svg.append('g');

    // Region nodes
    var nodes = sets.map(function (s, i) {
      var tags = (s && s.tags) ? s.tags : [];
      var tops = (s && s.top_mappers) ? s.top_mappers : [];
      return {
        id: (s && s.id != null) ? s.id : i,
        tags: tags,
        map_count: Number(s.map_count) || 0,
        top_mappers: tops,
        // initial position
        x: (w * 0.2) + (Math.random() * w * 0.6),
        y: (h * 0.2) + (Math.random() * h * 0.6)
      };
    });

    // Mapper list per tagset (used for nested treemap)
    nodes.forEach(function (n) {
      n._mappers = (n.top_mappers || []).slice(0, 60).map(function (m) {
        return { name: m.name, count: Number(m.count) || 0 };
      });
    });

    function hashHue(s) {
      s = safeText(s);
      var h = 0;
      for (var i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i);
      h = Math.abs(h) % 360;
      return h;
    }

    function mapperFill(name) {
      var hue = hashHue(name);
      return 'hsl(' + hue + ', 70%, 55%)';
    }

    // Note: area is still proportional to map_count within this viewport; zoom handles detail.

    // Build a treemap with exact area ratios (value = map_count)
    var root = d3.hierarchy({ children: nodes })
      .sum(function (d) { return Math.max(1, Number(d.map_count) || 0); })
      .sort(function (a, b) { return (b.value || 0) - (a.value || 0); });

    var treemap = d3.treemap()
      .size([w, h])
      .paddingInner(2)
      .paddingOuter(0)
      .tile(d3.treemapSquarify);
    treemap(root);

    var leaves = root.leaves();

    // Layers
    var regionG = zoomG.append('g').attr('class', 'regions');
    var bubbleG = zoomG.append('g').attr('class', 'region-bubbles');

    // defs for clip paths
    var defs = svg.select('defs');
    if (defs.empty()) defs = svg.append('defs');

    var clip = defs.selectAll('clipPath')
      .data(leaves, function (d) { return 'clip-' + d.data.id; });
    clip.exit().remove();
    var clipEnter = clip.enter().append('clipPath')
      .attr('id', function (d) { return 'clip-' + d.data.id; });
    clipEnter.append('rect');
    clip = clipEnter.merge(clip);
    clip.select('rect')
      .attr('x', function (d) { return d.x0; })
      .attr('y', function (d) { return d.y0; })
      .attr('width', function (d) { return Math.max(0, d.x1 - d.x0); })
      .attr('height', function (d) { return Math.max(0, d.y1 - d.y0); });

    // region rectangles
    var reg = regionG.selectAll('rect.region')
      .data(leaves, function (d) { return d.data.id; });
    reg.exit().remove();
    reg = reg.enter().append('rect')
      .attr('class', 'region')
      .merge(reg)
      .attr('x', function (d) { return d.x0; })
      .attr('y', function (d) { return d.y0; })
      .attr('width', function (d) { return Math.max(0, d.x1 - d.x0); })
      .attr('height', function (d) { return Math.max(0, d.y1 - d.y0); })
      .attr('fill', function (d) { return componentColor(Number(d.data.id) || 0); })
      .attr('opacity', 0.14)
      .attr('stroke', 'rgba(0,0,0,0.18)')
      .attr('stroke-width', 1.0);

    // nested mapper treemap clipped to the rect
    var cell = bubbleG.selectAll('g.cell')
      .data(leaves, function (d) { return d.data.id; });
    cell.exit().remove();
    var cellEnter = cell.enter().append('g').attr('class', 'cell');
    cell = cellEnter.merge(cell)
      .attr('clip-path', function (d) { return 'url(#clip-' + d.data.id + ')'; });

    cell.each(function (leaf) {
      var nd = leaf.data;
      var x0 = leaf.x0, y0 = leaf.y0, x1 = leaf.x1, y1 = leaf.y1;
      var pad = 4;
      var wCell = Math.max(0, (x1 - x0));
      var hCell = Math.max(0, (y1 - y0));
      // Header scales down for tiny sectors so it doesn't consume the whole box.
      // Keep a minimum so you can still visually see a "header" even for very small sectors.
      var headerH = clamp(hCell * 0.22, 6, 22);
      var headerFont = clamp(headerH * 0.60, 4, 11);

      // Header strip (tags)
      var header = d3.select(this).selectAll('g.header').data([leaf]);
      header.exit().remove();
      var headerEnter = header.enter().append('g').attr('class', 'header');
      headerEnter.append('rect').attr('class', 'header-bg');
      headerEnter.append('text').attr('class', 'header-text');
      header = headerEnter.merge(header);
      header.select('rect.header-bg')
        .attr('x', x0 + 1)
        .attr('y', y0 + 1)
        .attr('width', Math.max(0, wCell - 2))
        .attr('height', Math.min(headerH, Math.max(0, hCell - 2)))
        .attr('fill', (hCell <= 10) ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.55)');
      header.select('text.header-text')
        .attr('x', x0 + 6)
        .attr('y', y0 + (headerH * 0.75))
        .attr('fill', 'rgba(0,0,0,0.75)')
        .attr('font-weight', 800)
        .attr('font-size', headerFont)
        .attr('pointer-events', 'none')
        .text(function () {
          // Fit tags into the available width by truncating.
          var tags = (nd.tags || []);
          if (!tags.length) return '';
          var text = tags.join(', ');
          // Roughly estimate how many characters can fit (depends on font size).
          var maxChars = Math.max(3, Math.floor((wCell - 10) / Math.max(3, headerFont * 0.55)));
          if (text.length <= maxChars) return text;
          return text.slice(0, Math.max(0, maxChars - 1)) + '…';
        });

      var innerX = x0 + pad;
      var innerY = y0 + headerH + pad;
      var innerW = Math.max(0, wCell - pad * 2);
      var innerH = Math.max(0, hCell - headerH - pad * 2);
      // If there's essentially no space, just keep the tiny header and skip mapper rectangles.
      if (innerW <= 6 || innerH <= 6) return;

      // Nested treemap for mappers
      var mroot = d3.hierarchy({ children: (nd._mappers || []) })
        .sum(function (d) { return Math.max(1, Number(d.count) || 0); })
        .sort(function (a, b) { return (b.value || 0) - (a.value || 0); });
      d3.treemap()
        .size([innerW, innerH])
        .paddingInner(1)
        .tile(d3.treemapSquarify)(mroot);

      var mLeaves = mroot.leaves();
      var rects = d3.select(this).selectAll('g.mapper')
        .data(mLeaves, function (d) { return d.data.name; });
      rects.exit().remove();
      var rEnter = rects.enter().append('g').attr('class', 'mapper');
      rEnter.append('rect').attr('class', 'mapper-rect');
      rEnter.append('text').attr('class', 'mapper-text');
      rEnter.append('title');
      rects = rEnter.merge(rects);
      rects.attr('data-mapper', function (d) { return d.data.name; });

      rects.attr('transform', function (d) {
        return 'translate(' + (innerX + d.x0) + ',' + (innerY + d.y0) + ')';
      });
      rects.select('rect.mapper-rect')
        .attr('width', function (d) { return Math.max(0, d.x1 - d.x0); })
        .attr('height', function (d) { return Math.max(0, d.y1 - d.y0); })
        .attr('fill', function (d) { return mapperFill(d.data.name); })
        .attr('opacity', 0.45)
        .attr('stroke', 'rgba(0,0,0,0.18)')
        .attr('stroke-width', 1)
        .style('cursor', 'pointer')
        .on('mouseenter', function (ev, d) {
          try {
            tooltip.style.display = 'block';
            tooltip.innerHTML =
              '<div style="font-weight:700; margin-bottom:4px;">' + safeText(d.data.name) + '</div>' +
              '<div style="opacity:0.9;">Maps in this tagset: <b>' + safeText(d.data.count) + '</b></div>' +
              '<div style="opacity:0.85; margin-top:6px;">Tagset:</div>' +
              '<div style="opacity:0.95;">' + safeText((nd.tags || []).join(', ')) + '</div>' +
              '<div style="opacity:0.75; margin-top:6px;">Click to open search results</div>';
          } catch (e) { }
        })
        .on('mousemove', function (ev) {
          try { tooltip.style.left = (ev.clientX) + 'px'; tooltip.style.top = (ev.clientY) + 'px'; } catch (e) { }
        })
        .on('mouseleave', function () {
          try { tooltip.style.display = 'none'; } catch (e) { }
        })
        .on('click', function (ev, d) {
          // Click: select/deselect mapper globally (no navigation).
          try { ev.preventDefault(); ev.stopPropagation(); } catch (e) { }
          try { if (ev && ev.ctrlKey) return; } catch (e) { }
          try { if (window.__tagMapDidDrag) return; } catch (e) { }
          try {
            var name = safeText(d.data.name);
            if (window.__tagMapSelectedMapper === name) window.__tagMapSelectedMapper = null;
            else window.__tagMapSelectedMapper = name;
            try {
              var sel = window.__tagMapSelectedMapper;
              d3.select(container).selectAll('g.mapper')
                .classed('is-selected', function () { return sel && (this.getAttribute('data-mapper') === sel); })
                .classed('is-dimmed', function () { return sel && (this.getAttribute('data-mapper') !== sel); });
            } catch (e) {}
          } catch (e) { }
        })
        .on('dblclick', function (ev, d) {
          // Double-click: open search for mapper + this sector's tags.
          try { ev.preventDefault(); ev.stopPropagation(); } catch (e) { }
          try { if (ev && ev.ctrlKey) return; } catch (e) { }
          try { if (window.__tagMapDidDrag) return; } catch (e) { }
          try {
            var q = quoteIfNeeded(d.data.name);
            (nd.tags || []).forEach(function (t) {
              if (!t) return;
              var token = (/\s/.test(String(t)) ? ('."' + String(t).replace(/"/g, '\\"') + '"') : ('.' + String(t)));
              q += (q ? ' ' : '') + token;
            });
            window.location.href = '/search_results/?query=' + enc(q);
          } catch (e) { }
        });

      rects.select('text.mapper-text')
        .attr('x', 4)
        .attr('y', 14)
        .attr('fill', 'rgba(0,0,0,0.80)')
        .attr('font-weight', 800)
        .attr('font-size', function (d) {
          // Scale text to fit the rectangle
          var wR = Math.max(0, d.x1 - d.x0);
          var hR = Math.max(0, d.y1 - d.y0);
          var name = safeText(d.data.name);
          if (!name) return 0;
          // crude width estimate: ~0.6em per character
          var byW = (wR - 6) / Math.max(1, name.length * 0.6);
          var byH = (hR - 2) * 0.70;
          return clamp(Math.min(byW, byH, 14), 4, 14);
        })
        .attr('pointer-events', 'none')
        .text(function (d) { return safeText(d.data.name); })
        .each(function (d) {
          // Only hide if it's truly impossible to render anything.
          try {
            var wR = Math.max(0, d.x1 - d.x0);
            var hR = Math.max(0, d.y1 - d.y0);
            if (wR < 6 || hR < 6) d3.select(this).text('');
          } catch (e) { }
        });

      rects.select('title').text(function (d) { return d.data.name + ' (' + d.data.count + ')'; });
    });

    // Apply selection highlight (persists across reload/resize)
    try {
      var sel0 = window.__tagMapSelectedMapper;
      if (sel0) {
        d3.select(container).selectAll('g.mapper')
          .classed('is-selected', function () { return this.getAttribute('data-mapper') === sel0; })
          .classed('is-dimmed', function () { return this.getAttribute('data-mapper') !== sel0; });
      }
    } catch (e) {}

    if (statusEl) {
      statusEl.textContent =
        'Loaded ' + nodes.length + ' tagsets.';
    }
  }

  function init() {
    var container = $('tagMapContainer');
    var statusEl = $('tagMapStatus');
    var modeSel = $('tagMapMode');
    var statusSel = $('tagMapBeatmapStatus');
    var viewSel = $('tagMapView');
    var customInput = $('tagMapCustom');
    var btn = $('tagMapReloadBtn');
    var fsBtn = $('tagMapFullscreenBtn');
    var panel = $('tagMapPanel');

    if (!container || !statusEl || !modeSel || !statusSel || !viewSel || !customInput || !btn || !fsBtn || !panel) return;

    // Keep last payload so we can re-render on resize without refetching.
    var lastPayload = null;

    // Default layout zoom (persists for this page session)
    if (window.__tagMapLayoutZoom == null) window.__tagMapLayoutZoom = 1.0;

    // Fullscreen toggle (fullscreens the whole panel: controls + map)
    (function enableFullscreen() {
      function isFullscreen() {
        try { return !!document.fullscreenElement; } catch (e) { return false; }
      }
      function updateLabel() {
        try { fsBtn.textContent = isFullscreen() ? 'Exit fullscreen' : 'Fullscreen'; } catch (e) {}
      }
      fsBtn.addEventListener('click', function () {
        try {
          if (!document.fullscreenElement) {
            if (panel.requestFullscreen) panel.requestFullscreen();
          } else {
            if (document.exitFullscreen) document.exitFullscreen();
          }
        } catch (e) {}
      });
      document.addEventListener('fullscreenchange', function () {
        updateLabel();
        // Ensure tooltip element is inside the visible fullscreen subtree (or back on body when exiting).
        try {
          var tip = document.querySelector('.tagmap-tooltip');
          var fs = document.fullscreenElement;
          var panelEl = panel;
          if (tip && panelEl) {
            if (fs) {
              // In fullscreen: attach to panel so it renders.
              if (tip.parentNode !== panelEl) panelEl.appendChild(tip);
            } else {
              // Not fullscreen: attach to body (keeps it above everything site-wide).
              if (tip.parentNode !== document.body) document.body.appendChild(tip);
            }
          }
        } catch (e) {}
        // Re-render to adapt sizing to fullscreen/non-fullscreen layout.
        try { if (lastPayload) render(container, lastPayload, statusEl); } catch (e) {}
      });
      updateLabel();
    })();

    // Drag-to-pan (scroll the container with the mouse)
    // We also set a short-lived flag to suppress mapper click/dblclick if the user was dragging.
    (function enableDragPan() {
      try {
        container.style.cursor = 'grab';
      } catch (e) {}
      var isDown = false;
      var startX = 0, startY = 0;
      var startSL = 0, startST = 0;
      var didDrag = false;
      var DRAG_PX = 6;
      var didCapture = false;

      // Touch pinch/2-finger pan state (layout zoom + scroll)
      var touchPts = {};
      var pinchActive = false;
      var pinchStartDist = 0;
      var pinchStartMid = null;
      var pinchStartSL = 0;
      var pinchStartST = 0;
      var pinchStartZoom = 1.0;
      var rafPending = false;
      var pendingZoom = null;
      var pendingSL = null;
      var pendingST = null;

      function touchCount() {
        try { return Object.keys(touchPts).length; } catch (e) { return 0; }
      }

      function getTwoTouch() {
        var ids = Object.keys(touchPts);
        if (ids.length !== 2) return null;
        return [touchPts[ids[0]], touchPts[ids[1]]];
      }

      function dist(a, b) {
        var dx = (a.x - b.x);
        var dy = (a.y - b.y);
        return Math.sqrt(dx * dx + dy * dy);
      }

      function mid(a, b) {
        return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      }

      function scheduleApply() {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(function () {
          rafPending = false;
          try {
            if (pendingZoom != null) {
              window.__tagMapLayoutZoom = pendingZoom;
              pendingZoom = null;
              if (lastPayload) render(container, lastPayload, statusEl);
            }
            if (pendingSL != null) { container.scrollLeft = pendingSL; pendingSL = null; }
            if (pendingST != null) { container.scrollTop = pendingST; pendingST = null; }
          } catch (e) { /* no-op */ }
        });
      }

      function onDown(ev) {
        // Touch gestures: allow 2-finger pan + pinch zoom anywhere (even over mapper tiles).
        try {
          if (ev && ev.pointerType === 'touch') {
            touchPts[String(ev.pointerId)] = { x: ev.clientX || 0, y: ev.clientY || 0 };
            if (touchCount() === 2) {
              pinchActive = true;
              var pts = getTwoTouch();
              pinchStartMid = mid(pts[0], pts[1]);
              pinchStartDist = dist(pts[0], pts[1]) || 1;
              pinchStartSL = container.scrollLeft || 0;
              pinchStartST = container.scrollTop || 0;
              pinchStartZoom = Number(window.__tagMapLayoutZoom || 1.0) || 1.0;
              try { container.setPointerCapture(ev.pointerId); } catch (e) {}
            }
            return;
          }
        } catch (e) {}

        try {
          // Left mouse / primary pointer only
          if (ev.button != null && ev.button !== 0) return;
        } catch (e) {}
        // Allow drag-pan to start anywhere (including mapper tiles).
        // Click/dblclick are preserved because we only "commit" to drag after DRAG_PX movement,
        // and click handlers bail out when a drag occurred.

        isDown = true;
        didDrag = false;
        didCapture = false;
        startX = ev.clientX || 0;
        startY = ev.clientY || 0;
        startSL = container.scrollLeft || 0;
        startST = container.scrollTop || 0;
      }

      function onMove(ev) {
        // Touch pinch/2-finger pan (layout zoom + scroll)
        try {
          if (ev && ev.pointerType === 'touch' && touchPts[String(ev.pointerId)]) {
            touchPts[String(ev.pointerId)] = { x: ev.clientX || 0, y: ev.clientY || 0 };
            if (touchCount() === 2 && pinchActive) {
              try { ev.preventDefault(); } catch (e) {}
              var pts2 = getTwoTouch();
              var m2 = mid(pts2[0], pts2[1]);
              var d2 = dist(pts2[0], pts2[1]) || 1;

              var dxm = m2.x - (pinchStartMid ? pinchStartMid.x : m2.x);
              var dym = m2.y - (pinchStartMid ? pinchStartMid.y : m2.y);

              // Pan: move content opposite direction of finger movement
              var newSL = pinchStartSL - dxm;
              var newST = pinchStartST - dym;

              // Zoom: scale layout based on pinch distance
              var z0 = pinchStartZoom || 1.0;
              var z1 = clamp(z0 * (d2 / (pinchStartDist || 1)), 1.0, 6.0);
              var scale = z1 / z0;

              // Keep scroll feeling consistent under zoom scaling
              newSL = newSL * scale;
              newST = newST * scale;

              // Throttle rerender; always apply scroll
              pendingSL = newSL;
              pendingST = newST;
              if (Math.abs(z1 - (Number(window.__tagMapLayoutZoom || 1.0) || 1.0)) > 0.015) {
                pendingZoom = z1;
              }
              scheduleApply();
            }
            return;
          }
        } catch (e) {}

        if (!isDown) return;
        var x = ev.clientX || 0;
        var y = ev.clientY || 0;
        var dx = x - startX;
        var dy = y - startY;
        if (!didDrag && (Math.abs(dx) > DRAG_PX || Math.abs(dy) > DRAG_PX)) {
          didDrag = true;
          // Only capture once we *commit* to dragging; this avoids breaking click/dblclick.
          try { container.setPointerCapture(ev.pointerId); didCapture = true; } catch (e) { didCapture = false; }
          try { container.style.cursor = 'grabbing'; } catch (e) {}
        }
        if (!didDrag) return;
        try { ev.preventDefault(); } catch (e) {}
        container.scrollLeft = startSL - dx;
        container.scrollTop = startST - dy;
      }

      function onUp(ev) {
        // Touch end/cancel
        try {
          if (ev && ev.pointerType === 'touch') {
            delete touchPts[String(ev.pointerId)];
            if (touchCount() < 2) {
              pinchActive = false;
              pinchStartMid = null;
            }
            return;
          }
        } catch (e) {}

        if (!isDown) return;
        isDown = false;
        try { container.style.cursor = 'grab'; } catch (e) {}
        try { if (didCapture) container.releasePointerCapture(ev.pointerId); } catch (e) {}
        didCapture = false;
        if (didDrag) {
          window.__tagMapDidDrag = true;
          // Clear shortly after; click events fire after pointerup in most browsers.
          setTimeout(function () { window.__tagMapDidDrag = false; }, 160);
        }
      }

      // Pointer events cover mouse + touch + pen
      container.addEventListener('pointerdown', onDown, { passive: true });
      container.addEventListener('pointermove', onMove, { passive: false });
      container.addEventListener('pointerup', onUp, { passive: true });
      container.addEventListener('pointercancel', onUp, { passive: true });
      container.addEventListener('pointerleave', onUp, { passive: true });
    })();

    // Pull mode from URL if present (optional)
    try {
      var p = new URLSearchParams(window.location.search);
      var mode = p.get('mode');
      if (mode) modeSel.value = mode;
    } catch (e) { }

    function load() {
      statusEl.textContent = 'Loading…';
      // Consolidation is now fixed (best known-good value)
      var cons = 0.2;
      var custom = '';
      try { custom = String(customInput.value || '').trim(); } catch (e) { custom = ''; }
      var statusFilter = 'ranked';
      try { statusFilter = String(statusSel.value || 'ranked').trim().toLowerCase(); } catch (e) { statusFilter = 'ranked'; }
      var params = {
        mode: modeSel.value,
        status_filter: statusFilter,
        view: viewSel.value,
        custom_tagset: custom,
        consolidation: cons,
        max_tags: 150,
        // Note: max_sets/max_set_size/min_support/min_pair are driven by consolidation server-side
        max_mappers: 60
      };
      fetchTagMapData(params)
        .then(function (payload) {
          lastPayload = payload;
          render(container, payload, statusEl);
        })
        .catch(function (err) {
          statusEl.textContent = 'Failed to load: ' + (err && err.message ? err.message : String(err));
        });
    }

    btn.addEventListener('click', load);
    modeSel.addEventListener('change', load);
    statusSel.addEventListener('change', load);
    viewSel.addEventListener('change', load);

    // Custom tagset: debounce reload while typing; Enter triggers immediate reload.
    (function () {
      var t = null;
      function schedule() {
        if (t) { try { clearTimeout(t); } catch (e) {} }
        t = setTimeout(load, 220);
      }
      customInput.addEventListener('input', schedule);
      customInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          try { e.preventDefault(); } catch (e2) {}
          load();
        }
      });
    })();

    // Tag autocomplete for the custom tagset field (same token rules as search query autocomplete).
    (function enableCustomTagAutocomplete() {
      var list = document.createElement('ul');
      list.className = 'tag-list tag-portal';
      list.style.display = 'none';
      list.setAttribute('aria-live', 'polite');
      document.body.appendChild(list);

      var activeIndex = -1;
      var lastReq = 0;
      var debounceTimer = null;

      function updatePos() {
        var el = customInput;
        if (!el) return;
        var rect = el.getBoundingClientRect();
        var left = Math.max(0, rect.left);
        var top = rect.bottom + 4;
        var width = Math.min(rect.width, 520);
        var viewportH = (window.innerHeight || document.documentElement.clientHeight || 800);
        var maxH = Math.min(300, Math.max(120, (viewportH - rect.bottom - 12)));
        try {
          list.style.left = left + 'px';
          list.style.top = top + 'px';
          list.style.width = width + 'px';
          list.style.maxHeight = maxH + 'px';
          list.style.position = 'fixed';
          list.style.zIndex = '9999';
        } catch (e) {}
      }

      function openList() {
        updatePos();
        list.style.display = 'block';
      }

      function closeList() {
        activeIndex = -1;
        try { list.style.display = 'none'; } catch (e) {}
        list.innerHTML = '';
      }

      function setActive(idx) {
        var items = list.querySelectorAll('li');
        if (!items || !items.length) { activeIndex = -1; return; }
        activeIndex = Math.max(0, Math.min(idx, items.length - 1));
        for (var i = 0; i < items.length; i++) items[i].classList.remove('is-active');
        var el = items[activeIndex];
        if (el) {
          el.classList.add('is-active');
          try { if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest' }); } catch (e) {}
        }
      }

      function getTokenCtx() {
        var text = String(customInput.value || '');
        var cursor = (typeof customInput.selectionStart === 'number') ? customInput.selectionStart : text.length;
        var left = text.slice(0, cursor);
        var m = left.match(/(^|\s)([.\-]?\"[^\"]*|[.\-]?[^\s\"]*)$/);
        if (!m) return null;
        var token = m[2] || '';
        var tokenStart = cursor - token.length;
        var prefix = '';
        if (token[0] === '.' || token[0] === '-') {
          prefix = token[0];
          token = token.slice(1);
          tokenStart += 1;
        }
        var inQuote = false;
        if (token[0] === '"') {
          inQuote = true;
          token = token.slice(1);
          tokenStart += 1;
        }
        var q = token.trim();
        if (!q) return null;
        return { fullText: text, cursor: cursor, tokenStart: tokenStart, prefix: prefix, inQuote: inQuote, tokenQuery: q };
      }

      function renderResults(ctx, data) {
        list.innerHTML = '';
        activeIndex = -1;
        var arr = (data && data.length) ? data.slice(0, 12) : [];
        for (var i = 0; i < arr.length; i++) {
          var tag = arr[i];
          var name = tag && tag.name ? String(tag.name) : '';
          if (!name) continue;
          var count = (tag && typeof tag.beatmap_count === 'number') ? tag.beatmap_count : null;
          var label = (count == null) ? name : (name + ' (' + count + ')');
          var li = document.createElement('li');
          li.textContent = label;
          li.setAttribute('data-tag-name', name);
          list.appendChild(li);
        }
        if (list.children.length) openList();
        else closeList();
      }

      function applySuggestion(tagName) {
        var ctx = getTokenCtx();
        if (!ctx) return;
        var needsQuote = /\s/.test(tagName);
        var replacementCore = needsQuote ? ('"' + tagName.replace(/"/g, '') + '"') : tagName;
        var replacement = ctx.prefix + replacementCore;
        var before = ctx.fullText.slice(0, ctx.tokenStart);
        var after = ctx.fullText.slice(ctx.cursor);
        var newText = before + replacement + after;
        var nextChar = after.slice(0, 1);
        if (nextChar && !/\s/.test(nextChar)) newText = before + replacement + ' ' + after;
        else if (!nextChar) newText = before + replacement + ' ';
        customInput.value = newText;
        try {
          var pos = (before + replacement + ' ').length;
          customInput.setSelectionRange(pos, pos);
        } catch (e) {}
        closeList();
        // Re-run load quickly so the user immediately sees the updated custom sector.
        try { load(); } catch (e) {}
      }

      function searchTags(ctx) {
        var q = ctx.tokenQuery;
        if (!q || q.length < 2) { closeList(); return; }
        var reqId = ++lastReq;
        var modeVal = '';
        try { modeVal = String(modeSel.value || '').trim().toLowerCase(); } catch (e) { modeVal = ''; }
        fetch('/search_tags/?q=' + encodeURIComponent(q) + '&mode=' + encodeURIComponent(modeVal), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) { if (reqId === lastReq) renderResults(ctx, data); })
          .catch(function () { if (reqId === lastReq) closeList(); });
      }

      customInput.addEventListener('input', function () {
        if (debounceTimer) { try { clearTimeout(debounceTimer); } catch (e) {} }
        debounceTimer = setTimeout(function () {
          var ctx = getTokenCtx();
          if (!ctx) { closeList(); return; }
          searchTags(ctx);
        }, 90);
      });

      customInput.addEventListener('focus', function () {
        if (list.children.length) openList();
      });

      customInput.addEventListener('blur', function () {
        setTimeout(closeList, 120);
      });

      customInput.addEventListener('keydown', function (e) {
        if (list.style.display !== 'block') return;
        var items = list.querySelectorAll('li');
        if (!items || !items.length) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIndex + 1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIndex - 1); }
        else if (e.key === 'Enter') {
          if (activeIndex >= 0) {
            e.preventDefault();
            var it = items[activeIndex];
            var nm = it ? (it.getAttribute('data-tag-name') || '') : '';
            if (nm) applySuggestion(nm);
          }
        } else if (e.key === 'Escape') {
          e.preventDefault();
          closeList();
        }
      });

      list.addEventListener('mousedown', function (e) {
        // mousedown so it wins vs input blur
        try { e.preventDefault(); } catch (e2) {}
        var t = e.target;
        var li = (t && t.closest) ? t.closest('li') : null;
        if (!li) return;
        var nm = li.getAttribute('data-tag-name') || '';
        if (nm) applySuggestion(nm);
      });

      window.addEventListener('scroll', function () { if (list.style.display === 'block') updatePos(); }, { passive: true });
      window.addEventListener('resize', function () { if (list.style.display === 'block') updatePos(); }, { passive: true });
      document.addEventListener('mousedown', function (evt) {
        if (list.style.display !== 'block') return;
        var t = evt.target;
        if (t && (t === list || (t.closest && t.closest('ul.tag-portal')))) return;
        if (t && (t === customInput || (t.closest && t.closest('#tagMapCustom')))) return;
        closeList();
      });
    })();

    // Ctrl + mouse wheel: layout zoom in/out; container scroll remains normal otherwise.
    container.addEventListener('wheel', function (ev) {
      try {
        if (!ev.ctrlKey) return;
        ev.preventDefault();
      } catch (e) { return; }
      try {
        var z = Number(window.__tagMapLayoutZoom || 1.0) || 1.0;
        // Wheel down => zoom out, wheel up => zoom in
        var dir = (ev.deltaY || 0) > 0 ? -1 : 1;
        var step = 0.18;
        var next = clamp(z * (1.0 + (dir * step)), 1.0, 6.0);
        if (!lastPayload) return;

        // Zoom around cursor: keep the content point under the cursor stable.
        var rect = null;
        var pxView = 0, pyView = 0;
        var pxContent = 0, pyContent = 0;
        try {
          rect = container.getBoundingClientRect();
          pxView = (ev.clientX || 0) - (rect.left || 0);
          pyView = (ev.clientY || 0) - (rect.top || 0);
          pxContent = pxView + (container.scrollLeft || 0);
          pyContent = pyView + (container.scrollTop || 0);
        } catch (e) { rect = null; }

        window.__tagMapLayoutZoom = next;
        try { render(container, lastPayload, statusEl); } catch (e) { }

        // Apply corrected scroll after re-render
        try {
          var scale = next / (z || 1.0);
          var newSL = (pxContent * scale) - pxView;
          var newST = (pyContent * scale) - pyView;
          if (isFinite(newSL)) container.scrollLeft = Math.max(0, newSL);
          if (isFinite(newST)) container.scrollTop = Math.max(0, newST);
        } catch (e) { }
      } catch (e) { }
    }, { passive: false });

    // ResizeObserver: let the map pick width based on available space.
    // Re-render from cached payload so it updates immediately on resize.
    try {
      if (!window.__tagMapResizeObserver) {
        window.__tagMapResizeObserver = new ResizeObserver(function () {
          if (!lastPayload) return;
          try { render(container, lastPayload, statusEl); } catch (e) { }
        });
      }
      window.__tagMapResizeObserver.observe(container);
    } catch (e) { }

    load();
  }

  // Expose init for Statistics tab lazy-loading
  window.initTagMap = function () {
    try {
      if (window.__tagMapInitialized) return;
      window.__tagMapInitialized = true;
      init();
    } catch (e) { }
  };
})();


