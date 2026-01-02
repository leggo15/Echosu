// Autocomplete for the main search query input on Search Results page.
// Reuses the existing /search_tags/ endpoint and tagging.css dropdown styles.
(function ($) {
  if (!$) return;

  function initSearchQueryAutocomplete() {
    var $input = $('#tag-input');
    if (!$input.length) return;
    if ($input.data('search-autocomplete-initialized') === '1') return;
    $input.data('search-autocomplete-initialized', '1');

    var $mode = $('#mode');
    var $list = $('<ul class="tag-list tag-portal" aria-live="polite"></ul>').hide();
    $('body').append($list);

    var activeIndex = -1;
    var lastRequestId = 0;
    var debounceTimer = null;

    function updatePortalPosition() {
      var el = $input[0];
      if (!el) return;
      var rect = el.getBoundingClientRect();
      var left = Math.max(0, rect.left);
      var top = rect.bottom + 4;
      var width = Math.min(rect.width, 520);
      var viewportSpaceBelow = (window.innerHeight || document.documentElement.clientHeight) - rect.bottom - 12;
      var maxH = Math.min(300, Math.max(120, viewportSpaceBelow));
      $list.css({ left: left + 'px', top: top + 'px', width: width + 'px', maxHeight: maxH + 'px' });
    }

    function openList() {
      updatePortalPosition();
      $list.show();
    }

    function closeList() {
      activeIndex = -1;
      $list.hide().empty();
    }

    function setActiveIndex(idx) {
      var items = $list.children('li');
      if (!items.length) {
        activeIndex = -1;
        return;
      }
      activeIndex = Math.max(0, Math.min(idx, items.length - 1));
      items.removeClass('is-active');
      var $active = items.eq(activeIndex).addClass('is-active');
      // Ensure active item is visible
      try {
        var el = $active[0];
        if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
      } catch (e) { /* no-op */ }
    }

    // Extract the "current token" (word) at the cursor, respecting quotes and operator prefixes.
    function getCurrentTokenContext() {
      var text = String($input.val() || '');
      var cursor = $input[0] && typeof $input[0].selectionStart === 'number' ? $input[0].selectionStart : text.length;
      var left = text.slice(0, cursor);

      // Match the last token fragment after whitespace. Token can be:
      // - optional prefix '.' or '-'
      // - optional opening quote '"'
      // - then any non-space chars (or anything until closing quote if already opened)
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

      var query = token.trim();
      if (!query) return null;

      return {
        fullText: text,
        cursor: cursor,
        tokenStart: tokenStart,
        prefix: prefix,
        inQuote: inQuote,
        tokenQuery: query
      };
    }

    function renderResults(ctx, data) {
      $list.empty();
      activeIndex = -1;
      (data || []).slice(0, 12).forEach(function (tag) {
        var name = tag && tag.name ? String(tag.name) : '';
        if (!name) return;
        var count = (tag && typeof tag.beatmap_count === 'number') ? tag.beatmap_count : null;
        var label = count === null ? name : (name + ' (' + count + ')');
        $('<li></li>')
          .text(label)
          .attr('data-tag-name', name)
          .appendTo($list);
      });

      if ($list.children().length) openList();
      else closeList();
    }

    function searchTagsForToken(ctx) {
      var q = ctx.tokenQuery;
      if (!q) { closeList(); return; }

      // Keep traffic sane: don't hit API for single-letter tokens
      if (q.length < 2) { closeList(); return; }

      var modeVal = $mode.length ? String($mode.val() || '').trim().toLowerCase() : '';
      var reqId = ++lastRequestId;

      $.ajax({
        url: '/search_tags/',
        data: { q: q, mode: modeVal }
      }).done(function (data) {
        if (reqId !== lastRequestId) return; // stale response
        renderResults(ctx, data);
      }).fail(function () {
        if (reqId !== lastRequestId) return;
        closeList();
      });
    }

    function applySuggestion(tagName) {
      var ctx = getCurrentTokenContext();
      if (!ctx) return;

      var needsQuote = /\s/.test(tagName);
      var replacementCore = needsQuote ? ('"' + tagName.replace(/"/g, '') + '"') : tagName;
      var replacement = ctx.prefix + replacementCore;

      // Replace from tokenStart to cursor (only the currently typed fragment)
      var before = ctx.fullText.slice(0, ctx.tokenStart);
      var after = ctx.fullText.slice(ctx.cursor);
      var newText = before + replacement + after;

      // Add a space if the next char isn't already whitespace/end
      var nextChar = after.slice(0, 1);
      if (nextChar && !/\s/.test(nextChar)) {
        newText = before + replacement + ' ' + after;
      } else if (!nextChar) {
        newText = before + replacement + ' ';
      }

      $input.val(newText);
      try {
        var pos = (before + replacement + ' ').length;
        $input[0].setSelectionRange(pos, pos);
      } catch (e) { /* no-op */ }

      closeList();
    }

    // Input events
    $input.on('input', function () {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        var ctx = getCurrentTokenContext();
        if (!ctx) { closeList(); return; }
        searchTagsForToken(ctx);
      }, 90);
    });

    $input.on('focus', function () {
      // If we already have items rendered, reopen them positioned correctly.
      if ($list.children().length) openList();
    });

    $input.on('blur', function () {
      setTimeout(function () {
        closeList();
      }, 120);
    });

    $input.on('keydown', function (e) {
      if (!$list.is(':visible')) return;
      var items = $list.children('li');
      if (!items.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex(activeIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex(activeIndex - 1);
      } else if (e.key === 'Enter') {
        // Only hijack Enter if we have an active suggestion.
        if (activeIndex >= 0) {
          e.preventDefault();
          var name = items.eq(activeIndex).attr('data-tag-name') || '';
          if (name) applySuggestion(name);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeList();
      }
    });

    $list.on('mousedown', 'li', function (e) {
      // mousedown so it wins vs input blur
      e.preventDefault();
      var name = $(this).attr('data-tag-name') || '';
      if (name) applySuggestion(name);
    });

    // Keep positioned
    $(window).on('scroll resize', function () {
      if ($list.is(':visible')) updatePortalPosition();
    });

    // Close on outside click
    $(document).on('mousedown', function (evt) {
      if (!$list.is(':visible')) return;
      var $t = $(evt.target);
      if ($t.closest($list).length) return;
      if ($t.closest($input).length) return;
      closeList();
    });
  }

  $(document).ready(initSearchQueryAutocomplete);
})(window.jQuery);



