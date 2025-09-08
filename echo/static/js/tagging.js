// Tagging module: attaches behavior to any .tag-card instances
(function($) {
  // Global cache for bulk tag loading
  var tagCache = {};
  var pendingBulkRequests = {};
  // Track in-flight tag writes so we can wait before navigating
  var pendingTagWrites = 0;
  
  function attachTagging($card) {
    var beatmapId = $card.data('beatmap-id') || $card.attr('id')?.split('-').pop();
    var $wrapper = $card.closest('.beatmap-card-wrapper');
    if (!$wrapper.length) { $wrapper = $card.parent(); }
    // Scope interactive elements to the current card to avoid leaking across cards
    var $input = $card.find('.tag-input');
    var $list = $card.find('.tag-list');
    var $inputContainer = $input.closest('.tag-input-container');
    var $apply = $card.find('.apply-tag-btn');
    var $applied = $card.find('.applied-tags');
    // Admin-only negative tag controls (present only on beatmap_detail for staff)
    var $negInput = $card.find('.neg-tag-input');
    var $negList = $card.find('.neg-tag-list');
    var $negApply = $card.find('.apply-neg-tag-btn');
    var $negApplied = $card.find('.negative-tags');
    var csrf = $wrapper.find('input[name=csrfmiddlewaretoken]').val() || $('input[name=csrfmiddlewaretoken]').val();
    var isAuthenticated = Boolean(csrf);
    var refreshDebounceTimer = null;

    // -----------------------------
    // Dropdown portal helpers
    // -----------------------------
    function updatePortalPosition() {
      if (!$list.length || $list.data('portaled') !== '1' || !$inputContainer.length) return;
      var rect = $inputContainer[0].getBoundingClientRect();
      var left = Math.max(0, rect.left);
      var top = rect.bottom + 4; // match CSS spacing
      var width = Math.min(rect.width, 300); // limit dropdown width to 300px
      var viewportSpaceBelow = (window.innerHeight || document.documentElement.clientHeight) - rect.bottom - 12;
      var maxH = Math.min(300, Math.max(120, viewportSpaceBelow));
      $list.css({ left: left + 'px', top: top + 'px', width: width + 'px', maxHeight: maxH + 'px' });
    }

    function openPortal() {
      if (!$list.length || !$inputContainer.length) return;
      if ($list.data('portaled') === '1') { updatePortalPosition(); return; }
      $list.addClass('tag-portal');
      $('body').append($list);
      $list.data('portaled', '1');
      $inputContainer.addClass('portal-open');
      updatePortalPosition();
    }

    function closePortal() {
      if (!$list.length) return;
      if ($list.data('portaled') !== '1') return;
      // Restore to original container
      $list.removeClass('tag-portal');
      $list.css({ left: '', top: '', width: '', maxHeight: '' });
      $inputContainer.append($list);
      $list.data('portaled', '0');
      $inputContainer.removeClass('portal-open');
    }

    function searchTags(query) {
      if (!query) { $list.empty(); closePortal(); return; }
      $.ajax({ url: '/search_tags/', data: { q: query } })
        .done(function(data) {
          $list.empty();
          data.forEach(function(tag) {
            $('<li></li>').text(tag.name + ' (' + tag.beatmap_count + ')')
              .attr('data-tag-name', tag.name)
              .appendTo($list);
          });
          if (data && data.length) { openPortal(); } else { closePortal(); }
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
        data: { beatmap_id: beatmapId, include_predicted: includePredicted, include_true_negatives: 1 } 
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
      var mode = (window.TAG_CATEGORY_DISPLAY || 'color');
      $targetApplied.empty();
      if (mode !== 'lists') { $targetApplied.append('Tags: '); }
      // Split positives and negatives if provided
      var negatives = [];
      var positives = [];
      (Array.isArray(tags) ? tags : []).forEach(function(tag){
        if (tag && tag.true_negative) { negatives.push(tag); } else { positives.push(tag); }
      });

      // Render according to user preference
      // mode already computed above

      function renderTagInto($container, tag) {
        var tagClass = tag.is_applied_by_user ? 'tag-applied' : (tag.is_predicted && tag.apply_count === 0 ? 'tag-predicted' : 'tag-unapplied');
        var $el = $('<span></span>')
          .addClass('tag ' + tagClass)
          .attr('data-tag-name', tag.name)
          .attr('data-category', tag.category || 'other')
          .attr('data-applied-by-user', tag.is_applied_by_user)
          .attr('data-is-predicted', tag.is_predicted ? 'true' : 'false')
          .attr('data-true-negative', tag.true_negative ? 'true' : 'false')
          .attr('data-description', tag.description || '')
          .attr('data-description-author', tag.description_author || '')
          .attr('data-beatmap-id', beatmapId)
          .text(tag.name + (tag.apply_count ? ' (' + tag.apply_count + ')' : ''))
          .appendTo($container);
        if (mode === 'none') {
          $el.removeAttr('data-category');
        }
      }

      if (mode === 'lists') {
        var byCat = { mapping_genre: [], pattern_type: [], metadata: [], other: [] };
        positives.forEach(function(t){ var c = t.category || 'other'; (byCat[c] = byCat[c] || []).push(t); });
        var sections = [
          { key: 'mapping_genre', title: 'Mapping Genre' },
          { key: 'pattern_type', title: 'Pattern Type' },
          { key: 'metadata', title: 'Metadata' },
          { key: 'other', title: 'Other' }
        ];
        sections.forEach(function(sec){
          var lst = byCat[sec.key] || [];
          if (!lst.length) return;
          $('<div class="tag-section-title"></div>').text(sec.title + ':').appendTo($targetApplied);
          var $row = $('<div class="tag-section"></div>').appendTo($targetApplied);
          lst.forEach(function(t){ renderTagInto($row, t); });
        });
      } else {
        // color (default) or none (same layout)
        positives.forEach(function(tag){ renderTagInto($targetApplied, tag); });
      }

      // Render negatives if container present
      var $negTarget = $targetCard.find('.negative-tags');
      if ($negTarget.length) {
        $negTarget.empty().append('Negative Tags: ');
        negatives.forEach(function(tag) {
          $('<span></span>')
            .addClass('tag tag-negative')
            .attr('data-tag-name', tag.name)
            .attr('data-category', (window.TAG_CATEGORY_DISPLAY === 'none') ? null : (tag.category || 'other'))
            .attr('data-true-negative', 'true')
            .attr('data-beatmap-id', beatmapId)
            .text(tag.name)
            .appendTo($negTarget);
        });
      }
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

    function showConfigureTagModal(createdTag) {
      // Build lightweight floating modal in DOM (single instance)
      var $existing = $('#configure-tag-modal');
      if ($existing.length) { $existing.remove(); }
      var categories = [
        { value: 'mapping_genre', label: 'Mapping Genre' },
        { value: 'pattern_type', label: 'Pattern Type' },
        { value: 'metadata', label: 'Metadata' },
        { value: 'other', label: 'Other' }
      ];
      var $modal = $('<div id="configure-tag-modal" class="configure-tag-modal" role="dialog" aria-modal="true"></div>');
      var $box = $('<div class="configure-tag-box"></div>').appendTo($modal);
      var tagNameForHeader = (createdTag && createdTag.created_tag_name) ? createdTag.created_tag_name : 'Tag';
      $('<div class="configure-tag-title"></div>').text('"' + tagNameForHeader + '" is a New Tag').appendTo($box);
      var $body = $('<div class="configure-tag-body"></div>').appendTo($box);
      // Description input (top of form)
      var $descRow = $('<div class="row"></div>').appendTo($body);
      $('<label>Description</label>').appendTo($descRow);
      var $desc = $('<textarea class="configure-tag-description" rows="2" placeholder="Add a short description (max 100)"></textarea>').appendTo($descRow);
      // Category select
      var $catRow = $('<div class="row"></div>').appendTo($body);
      $('<label>Category</label>').appendTo($catRow);
      var $sel = $('<select class="configure-tag-category"></select>').appendTo($catRow);
      categories.forEach(function(c){ $('<option></option>').val(c.value).text(c.label).appendTo($sel); });
      // Parents input
      var $parRow = $('<div class="row"></div>').appendTo($body);
      $('<label>Associations</label>').appendTo($parRow);
      $('<input type="text" class="configure-tag-parents" placeholder="Enter related tags, comma separated" />').appendTo($parRow);
      // Tree container
      $('<div class="tree-label">Tag Tree</div>').appendTo($body);
      var $tree = $('<div class="configure-tag-tree"></div>').appendTo($body);
      // Footer
      var $footer = $('<div class="configure-tag-footer"></div>').appendTo($box);
      var $save = $('<button type="button" class="configure-tag-save">Save</button>').appendTo($footer);
      var $cancel = $('<button type="button" class="configure-tag-cancel">Cancel</button>').appendTo($footer);
      $('body').append($modal);

      // Load current tree (for display)
      $.get('/tag_tree/').done(function(resp){
        try {
          var tags = resp && resp.tags ? resp.tags : [];
          var cats = resp && resp.categories ? resp.categories : [];
          var byId = {}; tags.forEach(function(t){ byId[t.id] = t; });
          // Build categorized, collapsible tree
          function buildTree() {
            var byCat = {};
            tags.forEach(function(t){ var key = t.category || 'other'; (byCat[key] = byCat[key] || []).push(t); });
            var $root = $('<div class="tree-root"></div>');
            (cats && cats.length ? cats : [
              {value:'mapping_genre',label:'Mapping Genre'},
              {value:'pattern_type',label:'Pattern Type'},
              {value:'metadata',label:'Metadata'},
              {value:'other',label:'Other'}
            ]).forEach(function(cat){
              var lst = byCat[cat.value] || [];
              var $cat = $('<div class="tree-cat"></div>').appendTo($root);
              var $hdr = $('<div class="tree-cat-header" role="button" tabindex="0"></div>').text(cat.label).appendTo($cat);
              var $wrap = $('<div class="tree-cat-wrap"></div>').appendTo($cat);
              var $ul = $('<ul></ul>').appendTo($wrap);
              function addNode($parent, tag) {
                var $li = $('<li></li>').text(tag.name);
                $parent.append($li);
                var kids = tags.filter(function(tt){ return (tt.parent_ids || []).indexOf(tag.id) !== -1; });
                if (kids.length) {
                  var $childUl = $('<ul></ul>').appendTo($li);
                  kids.slice(0, 50).forEach(function(k){ addNode($childUl, k); });
                }
              }
              // roots within this category
              var roots = lst.filter(function(t){ return !t.parent_ids || t.parent_ids.length === 0; });
              roots.slice(0, 100).forEach(function(r){ addNode($ul, r); });
              // collapse by default
              $wrap.hide();
              $hdr.on('click keydown', function(e){ if (e.type === 'click' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $wrap.toggle(); } });
            });
            return $root;
          }
          $tree.empty().append(buildTree());
        } catch(e) { /* no-op */ }
      });

      // Wire actions
      $cancel.on('click', function(){ $modal.remove(); });
      $save.on('click', function(){
        var category = $sel.val();
        var parents = ($('.configure-tag-parents').val() || '').trim();
        var description = ($('.configure-tag-description').val() || '').trim();
        $.post('/configure_tag/', {
          csrfmiddlewaretoken: csrf,
          tag_id: createdTag.created_tag_id,
          category: category,
          parents: parents,
          description: description
        }).done(function(){
          $modal.remove();
          // Refresh the card tags to reflect any category-driven styles if added later
          refreshTagsIndividual(beatmapId);
        }).fail(function(err){
          alert((err.responseJSON && err.responseJSON.message) || 'Failed to configure tag');
        });
      });
    }

    function modifyTag($tagEl, tagName, action, isNegative) {
      if (!beatmapId) return;
      
      // Invalidate cache for this beatmap
      invalidateTagCache(beatmapId);
      
      pendingTagWrites += 1;
      $.ajax({
        type: 'POST', url: '/modify_tag/',
        data: { action: action, tag: tagName, beatmap_id: beatmapId, csrfmiddlewaretoken: csrf, true_negative: isNegative ? '1' : '0' }
      }).done(function(resp) {
        // Debounce UI refresh to coalesce rapid toggles, and update only this card.
        if (refreshDebounceTimer) { clearTimeout(refreshDebounceTimer); }
        refreshDebounceTimer = setTimeout(function(){
          refreshTagsIndividual(beatmapId);
          refreshDebounceTimer = null;
        }, 120);
        try {
          if (resp && resp.status === 'success' && resp.created === true && !isNegative) {
            // Newly created tag by this user: prompt for metadata
            showConfigureTagModal(resp);
          }
        } catch(e) { /* ignore */ }
      }).always(function(){
        pendingTagWrites = Math.max(0, pendingTagWrites - 1);
      });
    }

    // Events
    $input.on('input', function() { searchTags($(this).val()); });
    $input.on('focus', function(){ if ($list.children().length) { openPortal(); } });
    $input.on('blur', function(){ setTimeout(closePortal, 120); });
    $list.on('click', 'li', function() {
      var name = $(this).data('tag-name') || $(this).text().split(' (')[0];
      $input.val(name); $list.empty(); closePortal();
    });
    $input.on('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); $apply.click(); } });
    $apply.on('click', function() {
      if (!isAuthenticated) return; // require auth to modify
      var tagName = ($input.val() || '').trim();
      if (!tagName) return;
      var existing = $applied.find('.tag[data-tag-name="' + tagName + '"]');
      var action = existing.length && String(existing.attr('data-applied-by-user')).toLowerCase() === 'true' ? 'remove' : 'apply';
      modifyTag(existing, tagName, action, false);
    });

    $card.on('click', '.applied-tags .tag', function() {
      if (!isAuthenticated) return; // require auth to modify
      var $t = $(this);
      var tagName = $t.data('tag-name');
      var isAppliedByUser = String($t.attr('data-applied-by-user')).toLowerCase() === 'true';
      modifyTag($t, tagName, isAppliedByUser ? 'remove' : 'apply', false);
    });

    // Negative tag events (admin-only UI)
    $card.on('click', '.apply-neg-tag-btn', function() {
      if (!isAuthenticated) return; // still require auth
      var tagName = ($negInput.val() || '').trim();
      if (!tagName) return;
      var existing = $negApplied.find('.tag[data-tag-name="' + tagName + '"]');
      var action = existing.length ? 'remove' : 'apply';
      modifyTag(existing, tagName, action, true);
    });
    $card.on('click', '.negative-tags .tag', function() {
      if (!isAuthenticated) return;
      var $t = $(this);
      var tagName = $t.data('tag-name');
      modifyTag($t, tagName, 'remove', true);
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
      updatePortalPosition();
    });

    // Close on outside click for safety (per-card handler; cheap enough)
    $(document).on('mousedown', function(evt) {
      if (!$list.length) return;
      if ($list.data('portaled') !== '1') return;
      var $target = $(evt.target);
      if ($target.closest($list).length) return;
      if ($target.closest($inputContainer).length) return;
      closePortal();
    });

    // Initial fetch
    refreshTags();

    // PP Calculator functionality
    function initPPCalculator($card) {
      var beatmapId = $card.data('beatmap-id') || $card.attr('id')?.split('-').pop();
      var $calculator = $card.find('.pp-calculator');
      var $toggle = $calculator.find('.pp-calc-toggle');
      var $content = $calculator.find('.pp-calc-content');
      var $inputs = $calculator.find('.pp-calc-input');
      var $calculateBtn = $calculator.find('.pp-calc-calculate');
      
      var isExpanded = false;
      var hasInteracted = false;
      
      // Toggle calculator visibility
      $toggle.on('click', function() {
        isExpanded = !isExpanded;
        $content.toggle(isExpanded);
        $toggle.attr('aria-expanded', isExpanded);
      });
      
      
      // Calculate PP and update mod pills
      function calculateAndUpdatePP() {
        var data = {};
        var maxCombo = $calculator.data('max-combo') || 0;
        
        // Set default values
        data.combo = maxCombo;
        data.count_100 = 0;
        data.count_50 = 0;
        data.mods = '';
        
        // Get user input values
        $inputs.each(function() {
          var $input = $(this);
          var field = $input.data('field');
          var value = $input.val();
          
          if (field === 'count_miss') {
            data[field] = parseInt(value) || 0;
          } else if (field === 'accuracy') {
            data[field] = parseFloat(value) || 100.0;
          }
        });
        
        data.beatmap_id = beatmapId;
        
        // Show loading state
        $calculateBtn.prop('disabled', true).text('Calculating...');
        
        // Add updating animation to all PP pills
        $card.find('.pp-pill').addClass('updating');
        
        // Calculate PP for each mod combination
        var mods = ['', 'HD', 'HR', 'DT', 'HT', 'EZ', 'FL'];
        var modFields = ['pp_nomod', 'pp_hd', 'pp_hr', 'pp_dt', 'pp_ht', 'pp_ez', 'pp_fl'];
        var completed = 0;
        var results = {};
        
        mods.forEach(function(mod, index) {
          var requestData = Object.assign({}, data);
          if (mod) {
            requestData.mods = mod;
          }
          
          $.ajax({
            url: '/api/calculate-pp/',
            method: 'POST',
            data: JSON.stringify(requestData),
            contentType: 'application/json',
            headers: {
              'X-CSRFToken': csrf
            }
          }).done(function(response) {
            results[modFields[index]] = response.pp;
            completed++;
            
            // Update the corresponding PP pill
            var $pill = $card.find('.pp-' + (mod ? mod.toLowerCase() : 'nm'));
            if ($pill.length) {
              $pill.find('.pp-val').text(Math.round(response.pp));
              $pill.removeClass('updating');
            }
            
            // If all calculations are done, hide loading state
            if (completed === mods.length) {
              $calculateBtn.prop('disabled', false).text('Calculate');
              hasInteracted = true;
            }
          }).fail(function(xhr) {
            completed++;
            console.warn('Failed to calculate PP for mod:', mod, xhr.responseJSON);
            
            // Remove updating animation even on failure
            var $pill = $card.find('.pp-' + (mod ? mod.toLowerCase() : 'nm'));
            if ($pill.length) {
              $pill.removeClass('updating');
            }
            
            if (completed === mods.length) {
              $calculateBtn.prop('disabled', false).text('Calculate');
              if (completed === 1) { // Only show error if all failed
                var error = 'Failed to calculate PP';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                  error = xhr.responseJSON.error;
                }
                alert(error);
              }
            }
          });
        });
      }
      
      $calculateBtn.on('click', calculateAndUpdatePP);
      
      // Auto-calculate on input change (with debounce)
      var calcTimeout;
      $inputs.on('input', function() {
        hasInteracted = true;
        clearTimeout(calcTimeout);
        calcTimeout = setTimeout(function() {
          calculateAndUpdatePP();
        }, 500);
      });
      
      // Store max combo for reset functionality
      var maxCombo = $calculator.find('input[data-field="combo"]').attr('max');
      $calculator.data('max-combo', maxCombo);
    }
    
    // Initialize PP calculator for this card
    initPPCalculator($card);

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
        // For multi-owner input we preserve braces/commas; only prefill when EMPTY
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

    // Derive attribute filters from tag names (client-side mirror of backend mapping)
    function deriveFiltersFromTagsClient(tagNames) {
      var mapping = {
        'streams': ['bpm'],
        'speed': ['bpm'],
        'reading': ['ar'],
        'precision': ['cs'],
        'farm': ['accuracy', 'length', 'pp']
      };
      var suggested = {};
      (tagNames || []).forEach(function(name){
        var key = String(name || '').trim().toLowerCase();
        var attrs = mapping[key] || [];
        attrs.forEach(function(a){ suggested[a] = true; });
      });
      return Object.keys(suggested);
    }

    // Compute min/max windows for attributes based on values displayed on the card
    function computeWindowsFromCard($localCard) {
      // Star rating window (±15%)
      var starText = $localCard.find('.beatmap-stats .focus-stat').first().text();
      var rating = parseFloatSafe(starText);
      var starMin = isFinite(rating) ? Math.max(0, rating * 0.85) : 0;
      var starMax = isFinite(rating) ? rating * 1.15 : 10;
      if (isFinite(rating) && starMin < 0.4) { starMin = 0.4; starMax = 0.4; }

      // Extract numeric stats from text
      function readStat(prefix) {
        var m = $localCard.find('.beatmap-stats span').filter(function(){ return new RegExp('^' + prefix + ':', 'i').test(($(this).text() || '').trim()); }).first().text();
        var v = parseFloatSafe(m);
        return isFinite(v) ? v : null;
      }
      var cs = readStat('CS');
      var hp = readStat('HP');
      var od = readStat('OD');
      var ar = readStat('AR');

      // BPM
      var bpmText = $localCard.find('.beatmap-stats .minor-stat').filter(function(){ return /^BPM:/i.test(($(this).text() || '').trim()); }).first().text();
      var bpm = parseFloatSafe(bpmText);
      bpm = isFinite(bpm) ? bpm : null;

      // Length (prefer seconds inside parentheses)
      var lenText = $localCard.find('.beatmap-stats .beatmap-length').first().text();
      var lengthSecs = parseIntFromParens(lenText);
      if (!isFinite(lengthSecs)) lengthSecs = parseFloatSafe(lenText);
      lengthSecs = isFinite(lengthSecs) ? lengthSecs : null;

      // PP: prefer NM, else max of visible pills
      var nmText = $localCard.find('.pp-pill .pp-mod').filter(function(){ return (/^NM$/i).test(($(this).text() || '').trim()); }).closest('.pp-pill').find('.pp-val').first().text();
      var ppNm = parseFloatSafe(nmText);
      ppNm = isFinite(ppNm) ? ppNm : null;
      var ppVals = [];
      $localCard.find('.pp-pill .pp-val').each(function(){
        var val = parseFloatSafe($(this).text());
        if (isFinite(val)) ppVals.push(val);
      });
      var ppValue = (ppNm !== null) ? ppNm : (ppVals.length ? Math.max.apply(null, ppVals) : null);

      // Windows per backend logic
      var windows = {
        star_min: starMin,
        star_max: starMax,
        bpm_min: bpm === null ? null : Math.max(0, bpm - 15.0),
        bpm_max: bpm === null ? null : Math.max(0, bpm + 15.0),
        ar_min: ar === null ? null : Math.max(0, ar - (1 - (ar - 1) * (1 - 0.3) / (10 - 1))),
        ar_max: ar === null ? null : Math.min(10, ar + (1 - (ar - 1) * (1 - 0.3) / (10 - 1))),
        drain_min: hp === null ? null : Math.max(0, hp - 0.8),
        drain_max: hp === null ? null : Math.min(10, hp + 0.8),
        cs_min: cs === null ? null : Math.max(0, cs - (cs * 0.09)),
        cs_max: cs === null ? null : Math.min(10, cs + (cs * 0.09)),
        accuracy_min: od === null ? null : Math.max(0, od - (1 - (od - 1) * (1 - 0.4) / (10 - 1))),
        accuracy_max: od === null ? null : Math.min(10, od + (1 - (od - 1) * (1 - 0.4) / (10 - 1))),
        length_min: lengthSecs === null ? null : Math.max(0, Math.floor(lengthSecs - (lengthSecs * 0.3))),
        length_max: lengthSecs === null ? null : Math.max(0, Math.ceil(lengthSecs + (lengthSecs * 0.3))),
        pp_min: ppValue === null ? null : Math.max(0, ppValue - (ppValue * 0.15)),
        pp_max: ppValue === null ? null : Math.max(0, ppValue + (ppValue * 0.15))
      };
      return windows;
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

    // Always-visible Find Similar Maps button
    $wrapper.on('click', '.find-similar-btn', function(e) {
      e.preventDefault();
      function waitForWrites(cb) {
        if (pendingTagWrites === 0) { cb(); return; }
        var t = setInterval(function(){
          if (pendingTagWrites === 0) { clearInterval(t); cb(); }
        }, 50);
      }
      waitForWrites(function(){
        // Respect include_predicted toggle from current URL
        var params = new URLSearchParams(window.location.search);
        var includePredicted = params.get('include_predicted');
        // Resolve context strictly from the clicked element to avoid cross-card mixups
        var $btn = $(e.currentTarget);
        var $localWrapper = $btn.closest('.beatmap-card-wrapper');
        var $localCard = $btn.closest('.tag-card');
        var localBeatmapId = $localWrapper.data('beatmap-id') || ($localCard.attr('id') ? $localCard.attr('id').split('-').pop() : beatmapId);
        $.ajax({
          type: 'GET',
          url: '/get_tags/',
          data: { beatmap_id: localBeatmapId, include_predicted: includePredicted }
        }).done(function(tags){
          try {
            var arr = Array.isArray(tags) ? tags : [];
            var top = arr.slice(0, 10);
            var tagTokens = top.map(function(t){
              var name = (t && t.name) ? String(t.name) : '';
              if (!name) return null;
              return /\s/.test(name) ? '"' + name.replace(/\"/g, '') + '"' : name;
            }).filter(Boolean);
            // Derive attribute filters based on tags and compute windows from card
            var tagNames = top.map(function(t){ return (t && t.name) ? String(t.name) : ''; }).filter(Boolean);
            var filters = deriveFiltersFromTagsClient(tagNames);
            var windows = computeWindowsFromCard($localCard);
            var attrTokens = [];
            function hasNumbers(minKey, maxKey) {
              var a = windows[minKey]; var b = windows[maxKey];
              return a !== null && b !== null && isFinite(a) && isFinite(b);
            }
            if (filters.indexOf('bpm') !== -1 && hasNumbers('bpm_min', 'bpm_max')) {
              attrTokens.push('BPM>=' + String(Math.floor(windows['bpm_min'])));
              attrTokens.push('BPM<=' + String(Math.ceil(windows['bpm_max'])));
            }
            if (filters.indexOf('ar') !== -1 && hasNumbers('ar_min', 'ar_max')) {
              attrTokens.push('AR>=' + fmt(windows['ar_min'], 1));
              attrTokens.push('AR<=' + fmt(windows['ar_max'], 1));
            }
            if (filters.indexOf('cs') !== -1 && hasNumbers('cs_min', 'cs_max')) {
              attrTokens.push('CS>=' + fmt(windows['cs_min'], 1));
              attrTokens.push('CS<=' + fmt(windows['cs_max'], 1));
            }
            if (filters.indexOf('drain') !== -1 && hasNumbers('drain_min', 'drain_max')) {
              attrTokens.push('HP>=' + fmt(windows['drain_min'], 1));
              attrTokens.push('HP<=' + fmt(windows['drain_max'], 1));
            }
            if (filters.indexOf('accuracy') !== -1 && hasNumbers('accuracy_min', 'accuracy_max')) {
              attrTokens.push('OD>=' + fmt(windows['accuracy_min'], 1));
              attrTokens.push('OD<=' + fmt(windows['accuracy_max'], 1));
            }
            if (filters.indexOf('length') !== -1 && hasNumbers('length_min', 'length_max')) {
              attrTokens.push('LENGTH>=' + String(Math.max(0, Math.floor(windows['length_min']))));
              attrTokens.push('LENGTH<=' + String(Math.max(0, Math.ceil(windows['length_max']))));
            }
            if (filters.indexOf('pp') !== -1 && hasNumbers('pp_min', 'pp_max')) {
              attrTokens.push('PP>=' + fmt(windows['pp_min'], 1));
              attrTokens.push('PP<=' + fmt(windows['pp_max'], 1));
            }
            var url = buildSearchUrl();
            var allTokens = tagTokens.concat(attrTokens);
            if (allTokens.length) { url.searchParams.set('query', allTokens.join(' ')); }
            else { url.searchParams.delete('query'); }
            // Derive a star window from displayed star rating (±15%)
            url.searchParams.set('star_min', fmt(windows.star_min, 2));
            url.searchParams.set('star_max', fmt(windows.star_max, 2));
            url.searchParams.set('sort', 'tag_weight');
            navTo(url);
          } catch (err) {
            var fallback = buildSearchUrl();
            var txt = $localCard.find('.beatmap-stats .focus-stat').first().text();
            var r = parseFloatSafe(txt);
            if (isFinite(r)) {
              var mn = Math.max(0, r * 0.85);
              var mx = r * 1.15;
              fallback.searchParams.set('star_min', fmt(mn, 2));
              fallback.searchParams.set('star_max', fmt(mx, 2));
            }
            fallback.searchParams.set('sort', 'tag_weight');
            navTo(fallback);
          }
        }).fail(function(){
          var url = buildSearchUrl();
          var starText = $localCard.find('.beatmap-stats .focus-stat').first().text();
          var rating = parseFloatSafe(starText);
          if (isFinite(rating)) {
            var smin = Math.max(0, rating * 0.85);
            var smax = rating * 1.15;
            url.searchParams.set('star_min', fmt(smin, 2));
            url.searchParams.set('star_max', fmt(smax, 2));
          }
          url.searchParams.set('sort', 'tag_weight');
          navTo(url);
        });
      });
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
    // Always ensure each visible card has its tag list rendered with categories
    if (allBeatmapIds.length === 0) return;
    // Attempt bulk first for performance, fall back to individual
    var $firstCard = $('.tag-card').first();
    if ($firstCard.length) {
      // Call the internal bulk loader via the first initialized instance if available
      try {
        // Try internal bulk API if attachTagging created it (legacy safety)
        refreshTagsBulk(allBeatmapIds);
        return;
      } catch (e) { /* ignore and fallback */ }
    }
    // Fallback: iterate and refresh individually (ensures category border attributes render)
    allBeatmapIds.forEach(function(id){ refreshTagsIndividual(id); });
  }
  
  // Auto-load tags when DOM is ready
  $(document).ready(function() {
    // Small delay to ensure all cards are rendered
    setTimeout(loadAllBeatmapTags, 100);
    // Also reload on visibility changes that commonly change content without full reload
    $(document).on('ajaxComplete', function(){ setTimeout(loadAllBeatmapTags, 50); });
    
    // Handle PP calc parameters from search
    if (window.PP_CALC_PARAMS) {
      setTimeout(function() {
        var params = window.PP_CALC_PARAMS;
        $('.pp-calculator').each(function() {
          var $calculator = $(this);
          var $accuracyInput = $calculator.find('input[data-field="accuracy"]');
          var $missInput = $calculator.find('input[data-field="count_miss"]');
          
          if (params.accuracy !== undefined && $accuracyInput.length) {
            $accuracyInput.val(params.accuracy);
          }
          if (params.misses !== undefined && $missInput.length) {
            $missInput.val(params.misses);
          }
          
          // Auto-calculate if parameters were provided
          if ((params.accuracy !== undefined || params.misses !== undefined) && $calculator.length) {
            // Expand the calculator
            $calculator.find('.pp-calc-content').show();
            $calculator.find('.pp-calc-toggle').attr('aria-expanded', 'true');
            
            // Trigger calculation
            $calculator.find('.pp-calc-calculate').click();
          }
        });
      }, 200); // Wait for calculators to be initialized
    }
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

