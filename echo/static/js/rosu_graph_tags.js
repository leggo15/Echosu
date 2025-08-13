(function () {
  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

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

  function initTagStamping() {
    var canvas = document.getElementById('rosuGraphCanvas');
    if (!canvas) return;
    var beatmapId = (document.querySelector('[data-beatmap-id]') || {}).getAttribute('data-beatmap-id')
                   || (window.location.pathname.match(/beatmap_detail\/(\d+)/) || [])[1];
    if (!beatmapId) return;
    var tsUrl = '/beatmap_detail/' + beatmapId + '/tag_timestamps/';
    var saveUrl = '/beatmap_detail/' + beatmapId + '/tag_timestamps/save/';

    // UI: container under canvas
    var container = document.createElement('div');
    container.className = 'tag-stamps-panel';
    container.innerHTML = '' +
      '<div class="tag-stamps-row">' +
        '<select id="tagPicker"><option value="">— Select tag to edit —</option></select>' +
        '<button id="saveTagIntervals" disabled>Save</button>' +
      '</div>' +
      '<div class="tag-stamps-legends"></div>' +
      '';
    canvas.parentNode.appendChild(container);

    var tagPicker = container.querySelector('#tagPicker');
    var saveBtn = container.querySelector('#saveTagIntervals');
    var legends = container.querySelector('.tag-stamps-legends');

    var dpr = window.devicePixelRatio || 1;
    var state = {
      canvas: canvas,
      editingTagId: '',
      intervals: [], // current editable intervals for selected tag
      pendingStart: null, // first click time while selecting
      hoverTime: null,
      plot: null, // set by rosu_graph.js via window.__ROSU_PLOT__
      consensus: [], // [{tag_id, tag_name, consensus_intervals}]
      user: [], // [{tag_id, tag_name, intervals}]
    };

    function pxToTime(pxX) {
      if (!state.plot) return 0;
      var x = pxX / (window.devicePixelRatio || 1);
      var minX = state.plot.minX, maxX = state.plot.maxX;
      var left = state.plot.padding.left, plotW = state.plot.plotW;
      var ratio = Math.max(0, Math.min(1, (x - left) / plotW));
      return minX + ratio * (maxX - minX);
    }

    function redrawOverlay() {
      // Expect rosu_graph.js to call this hook when it draws
      var ov = window.__ROSU_OVERLAY__;
      if (typeof ov === 'function') ov(state);
    }

    var colorMap = {}; // tag_id -> { band, fade }
    function recomputeColors(filteredTags) {
      // Assign unique hues spaced evenly for currently present tags (with intervals)
      var ids = (filteredTags || state.consensus || []).map(function (t) { return t.tag_id; });
      // Deduplicate while preserving order
      var seen = {};
      ids = ids.filter(function (id) { if (seen[id]) return false; seen[id] = true; return true; });
      var count = Math.max(1, ids.length);
      for (var i = 0; i < ids.length; i++) {
        var hue = (i * 360 / count) % 360;
        colorMap[ids[i]] = {
          band: 'hsla(' + hue + ', 80%, 60%, 0.55)',
          fade: 'hsla(' + hue + ', 80%, 60%, 0.25)'
        };
      }
    }
    function tagColor(tagId) { return colorMap[tagId] || { band: 'hsla(0,0%,60%,0.55)', fade: 'hsla(0,0%,60%,0.25)' }; }

    var visibility = {}; // tag_id -> bool

    function loadData() {
      fetch(tsUrl + '?user=me', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          state.consensus = data.tags || [];
          state.user = data.user || [];
          // populate tag picker with user's applied tags
          var options = ['<option value="">— Select tag to edit —</option>'];
          state.user.forEach(function (u) {
            options.push('<option value="' + u.tag_id + '">' + u.tag_name + '</option>');
          });
          tagPicker.innerHTML = options.join('');
          // Filter to tags that have consensus intervals
          var tagsWithIntervals = (state.consensus || []).filter(function (t) {
            return (t.consensus_intervals || []).length > 0;
          });

          // Compute unique colors for current tag set
          recomputeColors(tagsWithIntervals);

          // Legends for toggling visibility (only those with intervals)
          var items = [];
          (tagsWithIntervals || []).forEach(function (t) {
            if (!(t.tag_id in visibility)) visibility[t.tag_id] = true;
            var colors = tagColor(t.tag_id);
            items.push('<button class="tag-toggle" data-tag="' + t.tag_id + '" style="background:' + (visibility[t.tag_id] ? colors.band : 'transparent') + ';border-color:' + colors.band + '">' + t.tag_name + '</button>');
          });
          legends.innerHTML = items.join(' ');
          legends.querySelectorAll('.tag-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
              var id = this.getAttribute('data-tag');
              visibility[id] = !visibility[id];
              loadData(); // re-render buttons
              if (typeof window.__ROSUREFRESH__ === 'function') window.__ROSUREFRESH__();
            });
          });
          redrawOverlay();
        });
    }

    tagPicker.addEventListener('change', function () {
      state.editingTagId = this.value || '';
      saveBtn.disabled = !state.editingTagId;
      var found = state.user.find(function (u) { return String(u.tag_id) === String(state.editingTagId); });
      state.intervals = found ? (found.intervals || []).slice() : [];
      redrawOverlay();
    });

    canvas.addEventListener('contextmenu', function (e) {
      // Right-click to remove nearest interval if editing
      if (!state.editingTagId) return;
      e.preventDefault();
      var rect = canvas.getBoundingClientRect();
      var x = (e.clientX - rect.left) * (window.devicePixelRatio || 1);
      var t = pxToTime(x);
      var bestIdx = -1, bestDist = Infinity;
      state.intervals.forEach(function (iv, idx) {
        var mid = (iv[0] + iv[1]) / 2;
        var d = Math.abs(mid - t);
        if (d < bestDist) { bestDist = d; bestIdx = idx; }
      });
      if (bestIdx >= 0) {
        state.intervals.splice(bestIdx, 1);
        state.pendingStart = null;
        redrawOverlay();
      }
    });

    // Single-click start/end selection
    canvas.addEventListener('mousedown', function (e) {
      if (!state.editingTagId || e.button !== 0) return;
      var rect = canvas.getBoundingClientRect();
      var x = (e.clientX - rect.left) * (window.devicePixelRatio || 1);
      var t = pxToTime(x);
      if (state.pendingStart == null) {
        state.pendingStart = t;
        redrawOverlay();
        return;
      }
      // Second click: finalize interval
      var t1 = state.pendingStart;
      var t2 = t;
      state.pendingStart = null;
      if (Math.abs(t2 - t1) < 0.25) return; // ignore clicks too small
      var s = Math.min(t1, t2), e2 = Math.max(t1, t2);
      // merge if overlapping
      var merged = [];
      var placed = false;
      for (var i = 0; i < state.intervals.length; i++) {
        var iv = state.intervals[i];
        if (e2 < iv[0] || s > iv[1]) {
          merged.push(iv);
        } else {
          s = Math.min(s, iv[0]);
          e2 = Math.max(e2, iv[1]);
        }
      }
      merged.push([s, e2]);
      merged.sort(function(a,b){return a[0]-b[0];});
      // second pass to merge adjacent
      var out = [];
      var cs = merged[0][0], ce = merged[0][1];
      for (var j = 1; j < merged.length; j++) {
        var iv2 = merged[j];
        if (iv2[0] <= ce) ce = Math.max(ce, iv2[1]);
        else { out.push([cs, ce]); cs = iv2[0]; ce = iv2[1]; }
      }
      out.push([cs, ce]);
      state.intervals = out;
      redrawOverlay();
    });
    canvas.addEventListener('mousemove', function (e) {
      // Always track hover for non-editing highlights and editing previews
      var rect = canvas.getBoundingClientRect();
      var x = (e.clientX - rect.left) * (window.devicePixelRatio || 1);
      state.hoverTime = pxToTime(x);
      if (state.editingTagId && state.pendingStart != null) redrawOverlay();
    });

    canvas.addEventListener('mouseleave', function () {
      // Clear hover and legend hover state when leaving the graph
      state.hoverTime = null;
      try {
        if (legends && legends.querySelectorAll) {
          legends.querySelectorAll('.tag-toggle').forEach(function (btn) {
            btn.classList.remove('hovered');
          });
        }
      } catch (e) { /* ignore */ }
      redrawOverlay();
    });

    saveBtn.addEventListener('click', function () {
      if (!state.editingTagId) return;
      fetch(saveUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': getCookie('csrftoken') || getCookie('CSRF-TOKEN') || ''
        },
        body: JSON.stringify({ tag_id: state.editingTagId, intervals: state.intervals, version: 1 }),
      }).then(function (r) { return r.json(); }).then(function () { loadData(); });
    });

    // Expose a hook for rosu_graph to provide plotting metrics and to draw overlay
    window.__SET_ROSU_PLOT__ = function (plot) { state.plot = plot; redrawOverlay(); };
    window.__ROSU_OVERLAY__ = function () {
      var ctx = canvas.getContext('2d');
      if (!state.plot) return;
      var dpr = window.devicePixelRatio || 1;
      var left = state.plot.padding.left;
      var top = state.plot.padding.top;
      var bottom = canvas.height - state.plot.padding.bottom;
      var plotW = state.plot.plotW;
      var minX = state.plot.minX, maxX = state.plot.maxX;
      function xScale(t) { return left + ((t - minX) / (maxX - minX || 1)) * plotW; }
      // Draw consensus bands (all tags)
      (state.consensus || []).forEach(function (tdata, idx) {
        if (visibility[tdata.tag_id] === false) return;
        var colors = tagColor(tdata.tag_id);
        (tdata.consensus_intervals || []).forEach(function (iv) {
          var x1 = xScale(iv[0]) * dpr, x2 = xScale(iv[1]) * dpr;
          ctx.fillStyle = colors.band;
          ctx.fillRect(x1, bottom - 6 * dpr, Math.max(1, x2 - x1), 6 * dpr);
          // gradient up
          var g = ctx.createLinearGradient(0, bottom - 6 * dpr, 0, top);
          g.addColorStop(0, colors.fade);
          g.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = g;
          ctx.fillRect(x1, top, Math.max(1, x2 - x1), bottom - top - 6 * dpr);
        });
      });
      // Draw editable intervals for selected tag on top
      if (state.editingTagId) {
        ctx.save();
        ctx.globalCompositeOperation = 'source-over';
        var selColor = 'rgba(255,255,255,0.85)';
        var bandHeight = 10 * dpr;
        (state.intervals || []).forEach(function (iv) {
          var x1 = xScale(iv[0]) * dpr, x2 = xScale(iv[1]) * dpr;
          // base band connecting bars
          ctx.fillStyle = 'rgba(255,255,255,0.25)';
          ctx.fillRect(x1, bottom - bandHeight, Math.max(1, x2 - x1), bandHeight);
          // soft fade upward over selected range
          var grad = ctx.createLinearGradient(0, bottom - bandHeight, 0, top);
          grad.addColorStop(0, 'rgba(255,255,255,0.18)');
          grad.addColorStop(1, 'rgba(255,255,255,0)');
          ctx.fillStyle = grad;
          ctx.fillRect(x1, top, Math.max(1, x2 - x1), bottom - top - bandHeight);
          // end bars
          ctx.fillStyle = selColor;
          ctx.fillRect(x1 - 1 * dpr, top, 2 * dpr, bottom - top);
          ctx.fillRect(x2 - 1 * dpr, top, 2 * dpr, bottom - top);
        });

        // Pending start marker + live preview
        if (state.pendingStart != null) {
          var psx = xScale(state.pendingStart) * dpr;
          // vertical bar that fades upward
          var barGrad = ctx.createLinearGradient(0, bottom, 0, top);
          barGrad.addColorStop(0, 'rgba(255,255,255,0.75)');
          barGrad.addColorStop(1, 'rgba(255,255,255,0)');
          ctx.fillStyle = barGrad;
          ctx.fillRect(psx - 1 * dpr, top, 2 * dpr, bottom - top);

          if (state.hoverTime != null && Math.abs(state.hoverTime - state.pendingStart) > 0.01) {
            var hx = xScale(state.hoverTime) * dpr;
            var x1p = Math.min(psx, hx), x2p = Math.max(psx, hx);
            // base connector
            ctx.fillStyle = 'rgba(255,255,255,0.25)';
            ctx.fillRect(x1p, bottom - bandHeight, Math.max(1, x2p - x1p), bandHeight);
            // soft region fade between bars
            var rgrad = ctx.createLinearGradient(0, bottom - bandHeight, 0, top);
            rgrad.addColorStop(0, 'rgba(255,255,255,0.12)');
            rgrad.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = rgrad;
            ctx.fillRect(x1p, top, Math.max(1, x2p - x1p), bottom - top - bandHeight);
            // second bar at hover
            ctx.fillStyle = selColor;
            ctx.fillRect(hx - 1 * dpr, top, 2 * dpr, bottom - top);
          }
        }
        ctx.restore();
      }

      // Hover tag name indicator + legend highlight only when NOT editing
      if (!state.editingTagId && state.hoverTime != null) {
        var t = state.hoverTime;
        var activeNames = [];
        var activeIds = [];
        (state.consensus || []).forEach(function (tdata) {
          if (visibility[tdata.tag_id] === false) return;
          var hit = (tdata.consensus_intervals || []).some(function (iv) { return t >= iv[0] && t <= iv[1]; });
          if (hit) { activeNames.push(tdata.tag_name); activeIds.push(String(tdata.tag_id)); }
        });
        // Highlight buttons for active tags
        try {
          if (legends && legends.querySelectorAll) {
            legends.querySelectorAll('.tag-toggle').forEach(function (btn) {
              var id = btn.getAttribute('data-tag');
              if (activeIds.indexOf(String(id)) !== -1) btn.classList.add('hovered');
              else btn.classList.remove('hovered');
            });
          }
        } catch (e) { /* ignore */ }
      } else {
        // Ensure legend hover is cleared when editing or when hover is not active
        try {
          if (legends && legends.querySelectorAll) {
            legends.querySelectorAll('.tag-toggle.hovered').forEach(function (btn) {
              btn.classList.remove('hovered');
            });
          }
        } catch (e) { /* ignore */ }
      }
    };

    loadData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTagStamping);
  } else {
    initTagStamping();
  }
})();


