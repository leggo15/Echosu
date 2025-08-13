// Global tooltips for tags outside of .tag-card (e.g., Top Tags on home)
(function($){
  $(document)
    .on('mouseenter', '.tags-usage .tag', function(){
      var tag = $(this);
      if (tag.closest('.tag-card').length) return; // handled by tagging.js
      var description = tag.data('description') || 'No description available.';
      var descriptionAuthor = tag.data('description-author') || '';
      var $tooltip = $('<div class="tooltip"></div>').text(description).appendTo('body');
      var $author = null;
      if (descriptionAuthor) { $author = $('<div class="description-author"></div>').text(descriptionAuthor).appendTo('body'); }
      var off = tag.offset(); var tw = $tooltip.outerWidth(); var th = $tooltip.outerHeight();
      var left = Math.max(10, Math.min(off.left + (tag.outerWidth()/2) - (tw/2), $(window).width() - tw - 10));
      var top = off.top - th - 8; $tooltip.css({ left: left, top: top, opacity: 1, position: 'absolute' });
      if ($author) { var rect = $tooltip[0].getBoundingClientRect(); $author.css({ left: rect.left + window.pageXOffset + rect.width - $author.outerWidth() - 4, top: rect.top + window.pageYOffset + rect.height - $author.outerHeight() + 2, opacity: 1, position: 'absolute', pointerEvents: 'none' }); }
      tag.data('tooltip', $tooltip); if ($author) tag.data('author', $author);
    })
    .on('mouseleave', '.tags-usage .tag', function(){
      var tag = $(this);
      var $tooltip = tag.data('tooltip'); var $author = tag.data('author');
      if ($tooltip) { $tooltip.remove(); tag.removeData('tooltip'); }
      if ($author) { $author.remove(); tag.removeData('author'); }
    });
})(jQuery);

