// Tagging module: attaches behavior to any .tag-card instances
(function($) {
  // Global cache for bulk tag loading
  var tagCache = {};
  var pendingBulkRequests = {};
  
  function attachTagging($card) {
    var beatmapId = $card.data('beatmap-id') || $card.attr('id')?.split('-').pop();
    var $wrapper = $card.closest('.beatmap-card-wrapper');
    if (!$wrapper.length) { $wrapper = $card.parent(); }
    // Scope interactive elements to the current card to avoid leaking across cards
    var $input = $card.find('.tag-input');
    var $list = $card.find('.tag-list');
    var $apply = $card.find('.apply-tag-btn');
    var $applied = $card.find('.applied-tags');
    var csrf = $wrapper.find('input[name=csrfmiddlewaretoken]').val() || $('input[name=csrfmiddlewaretoken]').val();
    var isAuthenticated = Boolean(csrf);
    var refreshDebounceTimer = null;

    function searchTags(query) {
      if (!query) { $list.empty(); return; }
      $.ajax({ url: '/search_tags/', data: { q: query } })
        .done(function(data) {
          $list.empty();
          data.forEach(function(tag) {
            $('<li></li>').text(tag.name + ' (' + tag.beatmap_count + ')')
              .attr('data-tag-name', tag.name)
              .appendTo($list);
          });
        });
    }

    // Bulk tag loading function
    function refreshTagsBulk(beatmapIds) {
      if (!beatmapIds || beatmapIds.length === 0) return;
      
      // Filter out beatmaps that already have cached tags
      var uncachedIds = beatmapIds.filter(function(id) {
        return !tagCache[id] || !tagCache[id].data;
      });
      
      if (uncachedIds.length === 0) {
        // All tags are cached, just update displays
        beatmapIds.forEach(function(id) {
          updateTagDisplay(id, tagCache[id].data);
        });
        return;
      }
      
      // Check if there's already a pending request for these IDs
      var requestKey = uncachedIds.sort().join(',');
      if (pendingBulkRequests[requestKey]) {
        // Wait for existing request to complete
        pendingBulkRequests[requestKey].push(function() {
          beatmapIds.forEach(function(id) {
            updateTagDisplay(id, tagCache[id].data);
          });
        });
        return;
      }
      
      // Create new pending request
      pendingBulkRequests[requestKey] = [];
      
      // Pull include_predicted from current URL params
      var params = new URLSearchParams(window.location.search);
      var includePredicted = params.get('include_predicted');
      
      $.ajax({ 
        type: 'GET', 
        url: '/get_tags_bulk/', 
        data: { beatmap_ids: uncachedIds, include_predicted: includePredicted }
      }).done(function(data) {
        // Cache the results
        uncachedIds.forEach(function(id) {
          tagCache[id] = {
            data: data.tags[id] || [],
            timestamp: Date.now()
          };
        });
        
        // Update displays for all requested beatmaps
        beatmapIds.forEach(function(id) {
          updateTagDisplay(id, tagCache[id].data);
        });
        
        // Execute pending callbacks
        var callbacks = pendingBulkRequests[requestKey];
        callbacks.forEach(function(callback) {
          try { callback(); } catch(e) { console.error('Tag callback error:', e); }
        });
        
        // Clean up
        delete pendingBulkRequests[requestKey];
      }).fail(function() {
        // On failure, fall back to individual requests
        console.warn('Bulk tag loading failed, falling back to individual requests');
        beatmapIds.forEach(function(id) {
          refreshTagsIndividual(id);
        });
        delete pendingBulkRequests[requestKey];
      });
    }

    // Individual tag loading (fallback)
    function refreshTagsIndividual(beatmapId) {
      if (!beatmapId) return;
      
      var params = new URLSearchParams(window.location.search);
      var includePredicted = params.get('include_predicted');
      
      $.ajax({ 
        type: 'GET', 
        url: '/get_tags/', 
        data: { beatmap_id: beatmapId, include_predicted: includePredicted } 
      }).done(function(tags) {
        // Cache the result
        tagCache[beatmapId] = {
          data: tags,
          timestamp: Date.now()
        };
        updateTagDisplay(beatmapId, tags);
      });
    }

    // Update tag display for a specific beatmap
    function updateTagDisplay(beatmapId, tags) {
      var $targetCard = $('#beatmap-' + beatmapId);
      if (!$targetCard.length) return;
      
      var $targetApplied = $targetCard.find('.applied-tags');
      if (!$targetApplied.length) return;
      
      $('.tooltip, .description-author').remove();
      $targetApplied.empty().append('Tags: ');
      
      tags.forEach(function(tag) {
        var tagClass = tag.is_applied_by_user ? 'tag-applied' : 
                      (tag.is_predicted ? 'tag-predicted' : 'tag-unapplied');
        
        $('<span></span>')
          .addClass('tag ' + tagClass)
          .attr('data-tag-name', tag.name)
          .attr('data-applied-by-user', tag.is_applied_by_user)
          .attr('data-is-predicted', tag.is_predicted ? 'true' : 'false')
          .attr('data-description', tag.description || '')
          .attr('data-description-author', tag.description_author || '')
          .attr('data-beatmap-id', beatmapId)
          .text(tag.name + (tag.apply_count ? ' (' + tag.apply_count + ')' : ''))
          .appendTo($targetApplied);
      });
    }

    // Main refresh function - tries bulk first, falls back to individual
    function refreshTags() {
      if (!beatmapId) return;
      
      // Try to use bulk loading if we have multiple beatmaps on the page
      var allBeatmapIds = $('.beatmap-card-wrapper').map(function() {
        return $(this).data('beatmap-id');
      }).get();
      
      if (allBeatmapIds.length > 1) {
        refreshTagsBulk(allBeatmapIds);
      } else {
        refreshTagsIndividual(beatmapId);
      }
    }

    // Cache invalidation when tags are modified
    function invalidateTagCache(beatmapId) {
      if (beatmapId && tagCache[beatmapId]) {
        delete tagCache[beatmapId];
      }
    }
    
    // Clear expired cache entries (older than 5 minutes)
    function clearExpiredCache() {
      var now = Date.now();
      var expiredIds = [];
      
      Object.keys(tagCache).forEach(function(id) {
        if (now - tagCache[id].timestamp > 5 * 60 * 1000) { // 5 minutes
          expiredIds.push(id);
        }
      });
      
      expiredIds.forEach(function(id) {
        delete tagCache[id];
      });
    }
    
    // Run cache cleanup every 5 minutes
    setInterval(clearExpiredCache, 5 * 60 * 1000);

    function modifyTag($tagEl, tagName, action) {
      if (!beatmapId) return;
      
      // Invalidate cache for this beatmap
      invalidateTagCache(beatmapId);
      
      $.ajax({
        type: 'POST', url: '/modify_tag/',
        data: { action: action, tag: tagName, beatmap_id: beatmapId, csrfmiddlewaretoken: csrf }
      }).done(function() {
        // Debounce UI refresh to coalesce rapid toggles, and update only this card.
        if (refreshDebounceTimer) { clearTimeout(refreshDebounceTimer); }
        refreshDebounceTimer = setTimeout(function(){
          refreshTagsIndividual(beatmapId);
          refreshDebounceTimer = null;
        }, 120);
      });
    }

    // Events
    $input.on('input', function() { searchTags($(this).val()); });
    $list.on('click', 'li', function() {
      var name = $(this).data('tag-name') || $(this).text().split(' (')[0];
      $input.val(name); $list.empty();
    });
    $input.on('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); $apply.click(); } });
    $apply.on('click', function() {
      if (!isAuthenticated) return; // require auth to modify
      var tagName = ($input.val() || '').trim();
      if (!tagName) return;
      var existing = $applied.find('.tag[data-tag-name="' + tagName + '"]');
      var action = existing.length && String(existing.attr('data-applied-by-user')).toLowerCase() === 'true' ? 'remove' : 'apply';
      modifyTag(existing, tagName, action);
    });

    $card.on('click', '.applied-tags .tag', function() {
      if (!isAuthenticated) return; // require auth to modify
      var $t = $(this);
      var tagName = $t.data('tag-name');
      var isAppliedByUser = String($t.attr('data-applied-by-user')).toLowerCase() === 'true';
      modifyTag($t, tagName, isAppliedByUser ? 'remove' : 'apply');
    });

    // Tooltip (shared with master.css styles)
    $card.on('mouseenter', '.applied-tags .tag, .tags-usage .tag', function() {
      var tag = $(this);
      tag.data('hovering', true);
      var description = tag.data('description') || 'No description available.';
      var descriptionAuthor = tag.data('description-author') || '';
      // Clear any existing tooltip to avoid duplicates
      var existing = tag.data('tooltip-element');
      if (existing) { existing.remove(); tag.removeData('tooltip-element'); }
      var existingAuthor = tag.data('author-element');
      if (existingAuthor) { existingAuthor.remove(); tag.removeData('author-element'); }
      var timeout = setTimeout(function() {
        // Only show if still hovering
        if (!tag.data('hovering')) return;
        if (tag.data('tooltip-visible')) return;
        var $tooltip = $('<div class="tooltip"></div>').text(description).appendTo('body').css({ opacity: 0, position: 'absolute', pointerEvents: 'none' });
        var $author = null;
        if (descriptionAuthor) {
          $author = $('<div class="description-author"></div>').text(descriptionAuthor).appendTo('body').css({ opacity: 0, position: 'absolute', pointerEvents: 'none' });
        }
        var off = tag.offset();
        var tw = $tooltip.outerWidth();
        var th = $tooltip.outerHeight();
        var left = Math.max(10, Math.min(off.left + (tag.outerWidth()/2) - (tw/2), $(window).width() - tw - 10));
        var top = off.top - th - 8;
        $tooltip.css({ left: left + 'px', top: top + 'px', opacity: '1' });
        if ($author) {
          var rect = $tooltip[0].getBoundingClientRect();
          var aLeft = rect.left + window.pageXOffset + rect.width - $author.outerWidth() - 4;
          var aTop = rect.top + window.pageYOffset + rect.height - $author.outerHeight() + 2;
          $author.css({ left: aLeft + 'px', top: aTop + 'px', opacity: '1' });
        }
        tag.data('tooltip-visible', true).data('tooltip-element', $tooltip);
        if ($author) tag.data('author-element', $author);
      }, 500);
      tag.data('tooltip-timeout', timeout);
    }).on('mouseleave', '.applied-tags .tag, .tags-usage .tag', function() {
      var tag = $(this);
      tag.data('hovering', false);
      var timeout = tag.data('tooltip-timeout');
      if (timeout) { clearTimeout(timeout); tag.removeData('tooltip-timeout'); }
      if (tag.data('tooltip-visible')) {
        var $tooltip = tag.data('tooltip-element');
        var $author = tag.data('author-element');
        if ($tooltip) { $tooltip.css('opacity', '0'); setTimeout(function(){ $tooltip && $tooltip.remove(); tag.removeData('tooltip-element'); }, 250); }
        if ($author) { $author.css('opacity', '0'); setTimeout(function(){ $author && $author.remove(); tag.removeData('author-element'); }, 250); }
        tag.removeData('tooltip-visible');
      }
    });

    // Safety cleanup on scroll/resize to prevent lingering tooltips
    $(window).on('scroll resize', function(){
      $('.tooltip, .description-author').remove();
      $card.find('.applied-tags .tag').each(function(){
        var t = $(this);
        t.removeData('tooltip-visible');
        t.removeData('tooltip-element');
        t.removeData('author-element');
        var tm = t.data('tooltip-timeout'); if (tm) { clearTimeout(tm); t.removeData('tooltip-timeout'); }
        t.data('hovering', false);
      });
    });

    // Initial fetch
    refreshTags();

    // Ownership edit inline controls
    $wrapper.on('click', '.mapper-edit-btn', function(){
      var $container = $(this).closest('.tag-card');
      var $input = $container.find('.mapper-edit-input');
      var $save = $container.find('.mapper-save-btn');
      $input.show();
      $save.show();
      $input.focus();
    });

    $wrapper.on('click', '.mapper-save-btn', function(){
      var $container = $(this).closest('.tag-card');
      var role = $container.find('.mapper-edit-btn').data('role');
      var $input = $container.find('.mapper-edit-input');
      var newOwnerId = ($input.val() || '').trim();
      // If listed owner: the backend requires set owner (id or name) to hand back
      if (role === 'listed_owner') {
        var setOwner = $container.find('.mapper-edit-btn').data('set-owner') || '';
        if (!newOwnerId) newOwnerId = setOwner;
      }
      if (!newOwnerId) return;
      var targetBeatmapId = $container.data('beatmap-id') || ($container.attr('id') ? $container.attr('id').split('-').pop() : beatmapId);
      $.post('/edit_ownership/', {
        beatmap_id: targetBeatmapId,
        new_owner: newOwnerId,
        csrfmiddlewaretoken: csrf
      }).done(function(resp){
        var name = resp.listed_owner || newOwnerId;
        var $disp = $container.find('.mapper-display');
        $disp.text(name);
        $input.hide();
        $container.find('.mapper-save-btn').hide();
      }).fail(function(err){
        alert((err.responseJSON && err.responseJSON.message) || 'Failed to update ownership');
      });
    });

    // Update map info action on card
    $wrapper.on('click', '.update-map-info-btn', function(e) {
      e.preventDefault();
      var url = $(this).data('update-url');
      if (!url || !beatmapId) return;
      $.post(url, { beatmap_id: beatmapId, csrfmiddlewaretoken: csrf })
        .done(function(){ location.reload(); })
        .fail(function(error){ alert('Failed to update: ' + (error.responseJSON && error.responseJSON.error)); });
    });

    // -----------------------------
    // Click-to-filter helpers
    // -----------------------------
    function buildSearchUrl() {
      var basePath = '/search_results/';
      var url = new URL(basePath, window.location.origin);
      try {
        var current = new URL(window.location.href);
        // Preserve existing params
        current.searchParams.forEach(function(value, key) {
          // Drop pagination when changing filters
          if (key === 'page') return;
          url.searchParams.set(key, value);
        });
      } catch (e) { /* no-op */ }
      return url;
    }

    function appendQueryTokens(url, tokens) {
      if (!tokens || !tokens.length) return url;
      var existing = url.searchParams.get('query') || '';
      var addition = tokens.join(' ').trim();
      var combined = (existing ? (existing + ' ') : '') + addition;
      url.searchParams.set('query', combined.trim());
      return url;
    }

    function toggleStatusParam(url, statusText) {
      var st = String(statusText || '').toLowerCase();
      var key = null, val = null;
      if (st.indexOf('ranked') !== -1 || st.indexOf('approved') !== -1) { key = 'status_ranked'; val = 'ranked'; }
      else if (st.indexOf('loved') !== -1) { key = 'status_loved'; val = 'loved'; }
      else { key = 'status_unranked'; val = 'unranked'; }
      if (url.searchParams.has(key)) { url.searchParams.delete(key); }
      else { url.searchParams.set(key, val); }
      return url;
    }

    function navTo(url) { window.location.href = url.toString(); }

    // Numeric parsing helpers
    function parseFloatSafe(text) {
      var m = String(text || '').match(/[-+]?[0-9]*\.?[0-9]+/);
      return m ? parseFloat(m[0]) : NaN;
    }
    function parseIntFromParens(text) {
      var m = String(text || '').match(/\((\d+)\)/);
      if (m) return parseInt(m[1], 10);
      var m2 = String(text || '').match(/(\d+)\s*$/);
      return m2 ? parseInt(m2[1], 10) : NaN;
    }

    function clamp(num, min, max) {
      return Math.max(min, Math.min(max, num));
    }

    function fmt(num, decimals) {
      var d = (typeof decimals === 'number') ? decimals : 1;
      var n = Number(num);
      if (!isFinite(n)) return '';
      return (d <= 0) ? String(Math.round(n)) : n.toFixed(d);
    }

    // PP mod pills (NM/HD/HR/DT/HT/EZ/FL) -> ±15%
    $card.on('click', '.pp-pill', function() {
      var $pill = $(this);
      var mod = ($pill.find('.pp-mod').text() || '').trim().toUpperCase();
      if (!mod) return;
      var val = parseFloatSafe($pill.find('.pp-val').text());
      if (!isFinite(val)) return;
      var min = Math.max(0, val * 0.85);
      var max = val * 1.15;
      var tokens = [mod + '>=' + fmt(min, 1), mod + '<=' + fmt(max, 1)];
      var url = buildSearchUrl();
      appendQueryTokens(url, tokens);
      navTo(url);
    });

    // Star rating (first focus-stat without status class) -> set star_min/star_max (±15%)
    $card.on('click', '.beatmap-stats .focus-stat', function() {
      var $el = $(this);
      if ($el.hasClass('status-pill')) return; // handled separately
      var text = $el.text().trim();
      if (text.indexOf('★') !== 0) return;
      var rating = parseFloatSafe(text);
      if (!isFinite(rating)) return;
      var starMin = Math.max(0, rating * 0.85);
      var starMax = rating * 1.15;
      var url = buildSearchUrl();
      url.searchParams.set('star_min', fmt(starMin, 2));
      url.searchParams.set('star_max', fmt(starMax, 2));
      navTo(url);
    });

    // Status pill -> toggle corresponding status_* param
    $card.on('click', '.beatmap-stats .status-pill', function() {
      var $el = $(this);
      var st = ($el.text() || '').trim();
      var url = buildSearchUrl();
      toggleStatusParam(url, st);
      navTo(url);
    });

    // CS/HP/OD/AR -> ±1.0
    $card.on('click', '.beatmap-stats span', function() {
      var t = ($(this).text() || '').trim();
      // Guard out non-stat spans
      if (/^\|$/.test(t)) return;
      var m = t.match(/^(CS|HP|OD|AR):\s*([0-9]*\.?[0-9]+)/i);
      if (!m) return;
      var key = m[1].toUpperCase();
      var val = parseFloat(m[2]);
      if (!isFinite(val)) return;
      var min = clamp(val - 1.0, 0, 10);
      var max = clamp(val + 1.0, 0, 10);
      var tokens = [key + '>=' + fmt(min, 1), key + '<=' + fmt(max, 1)];
      var url = buildSearchUrl();
      appendQueryTokens(url, tokens);
      navTo(url);
    });

    // BPM -> ±15%
    $card.on('click', '.beatmap-stats .minor-stat', function() {
      var text = ($(this).text() || '').trim();
      var url = buildSearchUrl();
      // BPM
      if (/^BPM:/i.test(text)) {
        var bpm = parseFloatSafe(text);
        if (!isFinite(bpm)) return;
        var bmin = Math.max(0, bpm * 0.85);
        var bmax = bpm * 1.15;
        appendQueryTokens(url, ['BPM>=' + fmt(bmin, 0), 'BPM<=' + fmt(bmax, 0)]);
        navTo(url);
        return;
      }
      // Length (seconds inside parentheses) -> ±15%
      if (/^Length:/i.test(text)) {
        var secs = parseIntFromParens(text);
        if (!isFinite(secs)) secs = parseFloatSafe(text);
        if (!isFinite(secs)) return;
        var lmin = Math.max(0, Math.floor(secs * 0.85));
        var lmax = Math.max(0, Math.ceil(secs * 1.15));
        appendQueryTokens(url, ['LENGTH>=' + String(lmin), 'LENGTH<=' + String(lmax)]);
        navTo(url);
        return;
      }
      // Year -> ±1
      if (/^Year:/i.test(text)) {
        var year = parseIntFromParens(text);
        if (!isFinite(year)) year = parseInt(String(text).replace(/[^0-9]/g, ''), 10);
        if (!isFinite(year)) return;
        appendQueryTokens(url, ['YEAR>=' + String(year - 1), 'YEAR<=' + String(year + 1)]);
        navTo(url);
        return;
      }
    });

    // Mapper click -> ."listed_owner"
    $wrapper.on('click', '.mapper-display', function() {
      var name = ($(this).text() || '').trim();
      if (!name) return;
      var needsQuote = /\s/.test(name);
      var token = needsQuote ? '"' + name.replace(/"/g, '') + '"' : '"' + name.replace(/"/g, '') + '"';
      var url = buildSearchUrl();
      appendQueryTokens(url, [token]);
      navTo(url);
    });

    // Artist click -> ."artist"
    $wrapper.on('click', 'h3.artist', function() {
      var raw = ($(this).text() || '').trim();
      var name = raw.replace(/^Artist:\s*/i, '').trim();
      if (!name) return;
      var token = '"' + name.replace(/"/g, '') + '"';
      var url = buildSearchUrl();
      appendQueryTokens(url, [token]);
      navTo(url);
    });
  }

  // Expose a global initializer for dynamically inserted cards
  window.initTaggingFor = function(root) {
    var $root = root ? $(root) : $(document);
    $root.find('.tag-card').each(function(index) {
      var $card = $(this);
      if ($card.data('tagging-initialized') === '1') return;
      $card.data('tagging-initialized', '1');
      if (index % 2 === 1) { $card.addClass('tag-card--alt'); }
      attachTagging($card);
    });
  };

  // Global function to load tags for all beatmaps on the page
  function loadAllBeatmapTags() {
    var allBeatmapIds = $('.beatmap-card-wrapper').map(function() {
      return $(this).data('beatmap-id');
    }).get();
    
    if (allBeatmapIds.length > 1) {
      // Use the first card's tagging instance to trigger bulk loading
      var $firstCard = $('.tag-card').first();
      if ($firstCard.length) {
        var taggingInstance = $firstCard.data('tagging-instance');
        if (taggingInstance && taggingInstance.refreshTagsBulk) {
          taggingInstance.refreshTagsBulk(allBeatmapIds);
        }
      }
    }
  }
  
  // Auto-load tags when DOM is ready
  $(document).ready(function() {
    // Small delay to ensure all cards are rendered
    setTimeout(loadAllBeatmapTags, 100);
  });

  // Expose functions globally for external use
  window.TagManager = {
    loadAllBeatmapTags: loadAllBeatmapTags,
    clearTagCache: function() {
      tagCache = {};
      pendingBulkRequests = {};
    }
  };

  $(function() { window.initTaggingFor(document); });
})(jQuery);

