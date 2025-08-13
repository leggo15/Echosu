// Tagging module: attaches behavior to any .tag-card instances
(function($) {
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

    function refreshTags() {
      if (!beatmapId) return;
      // Pull include_predicted from current URL params so cards reflect page toggle
      var params = new URLSearchParams(window.location.search);
      var includePredicted = params.get('include_predicted');
      $.ajax({ type: 'GET', url: '/get_tags/', data: { beatmap_id: beatmapId, include_predicted: includePredicted } })
        .done(function(tags) {
          $('.tooltip, .description-author').remove();
          $applied.empty().append('Tags: ');
          tags.forEach(function(tag) {
            var tagClass = tag.is_applied_by_user ? 'tag-applied' : (tag.is_predicted ? 'tag-predicted' : 'tag-unapplied');
            $('<span></span>')
              .addClass('tag ' + tagClass)
              .attr('data-tag-name', tag.name)
              .attr('data-applied-by-user', tag.is_applied_by_user)
              .attr('data-is-predicted', tag.is_predicted ? 'true' : 'false')
              .attr('data-description', tag.description || '')
              .attr('data-description-author', tag.description_author || '')
              .attr('data-beatmap-id', beatmapId)
              .text(tag.name + (tag.apply_count ? ' (' + tag.apply_count + ')' : ''))
              .appendTo($applied);
          });
          // Backend now decides whether to show "Find Similar Maps" and builds the query.
          // No client-side decision needed here.
        });
    }


    function modifyTag($tagEl, tagName, action) {
      if (!beatmapId) return;
      $.ajax({
        type: 'POST', url: '/modify_tag/',
        data: { action: action, tag: tagName, beatmap_id: beatmapId, csrfmiddlewaretoken: csrf }
      }).done(function() { refreshTags(); });
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
      var $btn = $(this);
      var $input = $card.find('.mapper-edit-input');
      var $save = $card.find('.mapper-save-btn');
      $input.show();
      $save.show();
      $input.focus();
    });

    $wrapper.on('click', '.mapper-save-btn', function(){
      var role = $card.find('.mapper-edit-btn').data('role');
      var $input = $card.find('.mapper-edit-input');
      var newOwnerId = ($input.val() || '').trim();
      // If listed owner: the backend requires set owner (id or name) to hand back
      if (role === 'listed_owner') {
        var setOwner = $card.find('.mapper-edit-btn').data('set-owner') || '';
        // When handing back, allow prefill with set owner id if input empty
        if (!newOwnerId) newOwnerId = setOwner;
      }
      if (!newOwnerId) return;
      $.post('/edit_ownership/', {
        beatmap_id: beatmapId,
        new_owner: newOwnerId,
        csrfmiddlewaretoken: csrf
      }).done(function(resp){
        // Update mapper text inline
        var name = resp.listed_owner || newOwnerId;
        var $disp = $card.find('.mapper-display');
        $disp.text(name);
        // Reset UI
        $input.hide();
        $card.find('.mapper-save-btn').hide();
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

  $(function() { window.initTaggingFor(document); });
})(jQuery);

