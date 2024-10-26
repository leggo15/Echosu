$(document).ready(function() { 
    var selectedTag;

    // Tag input functionality
    $('#tag-input').on('input', function() {
        var inputVal = $(this).val();
        if (inputVal.length > 0) {
            $.ajax({
                url: '/search_tags/',
                data: { 'q': inputVal },
                success: function(data) {
                    $('#tag-list').empty();
                    data.forEach(function(tag) {
                        $('#tag-list').append(`<li>${tag.name} (${tag.beatmap_count})</li>`);
                    });
                },
                error: function(xhr, status, error) {
                    console.error('AJAX error:', status, error);
                }
            });
        } else {
            $('#tag-list').empty();
            selectedTag = null;
        }
    });

    // Tag suggestion click
    $('#tag-list').on('click', 'li', function() {
        selectedTag = $(this).text().split(' (')[0];
        $('#tag-input').val(selectedTag);
        $('#tag-list').empty();
    });

    // Apply tag button click
    $('.apply-tag-btn').on('click', function() {
        var tagName = $('#tag-input').val();
        if (tagName) {
            var beatmapId = $('#current_beatmap_id').val();
            if (beatmapId) {
                // Find the tag element in the Beatmap Info section
                var $tagElement = $('#beatmap-applied-tags .tag[data-tag-name="' + tagName + '"]');
                if ($tagElement.length === 0) {
                    // If the tag doesn't exist yet, create a new tag element
                    $tagElement = $('<span></span>')
                        .addClass('tag tag-applied')
                        .attr('data-tag-name', tagName)
                        .attr('data-applied-by-user', true)
                        .attr('data-beatmap-id', beatmapId)
                        .text(`${tagName} (1)`)
                        .appendTo('#beatmap-applied-tags');
                }
                modifyTag($tagElement, tagName, beatmapId, 'apply');
            } else {
                alert('No beatmap selected.');
            }
        } else {
            alert('Please enter a tag name.');
        }
    });

    // Attach click event to all tags within .applied-tags using event delegation
    $(document).on('click', '.applied-tags .tag', function() {
        var $this = $(this);
        var tagName = $this.data('tag-name');
        var beatmapId = $this.data('beatmap-id');
        var isAppliedByUser = $this.attr('data-applied-by-user') === 'true';
        var action = isAppliedByUser ? 'remove' : 'apply';
        modifyTag($this, tagName, beatmapId, action);
    });

    // Modify tag function
    function modifyTag($tagElement, tagName, beatmapId, action) {
        $.ajax({
            type: 'POST',
            url: '/modify_tag/',
            data: {
                'action': action,
                'tag': tagName,
                'beatmap_id': beatmapId,
                'csrfmiddlewaretoken': $('input[name=csrfmiddlewaretoken]').val()
            },
            success: function(response) {
                // Update the tag's attributes and class
                var isApplied = (action === 'apply');
                $tagElement.attr('data-applied-by-user', isApplied);
                if (isApplied) {
                    $tagElement.removeClass('tag-unapplied').addClass('tag-applied');
                } else {
                    $tagElement.removeClass('tag-applied').addClass('tag-unapplied');
                }

                // Update the apply_count displayed
                var text = $tagElement.text();
                var match = text.match(/\((\d+)\)/);
                if (match) {
                    var applyCount = parseInt(match[1]);
                    applyCount = isApplied ? applyCount + 1 : applyCount - 1;
                    applyCount = Math.max(applyCount, 0); // Ensure applyCount doesn't go below 0
                    $tagElement.text(`${tagName} (${applyCount})`);
                }

                // If this is the current beatmap in Beatmap Info Section, refresh tags to get accurate counts
                if (beatmapId == $('#current_beatmap_id').val()) {
                    refreshTags();
                }
            },
            error: function(xhr, status, error) {
                console.error('AJAX error:', status, error, xhr.responseText);
            }
        });
    }

    // Refresh tags in the Beatmap Info section
    function refreshTags() {
        var beatmapId = $('#current_beatmap_id').val();
        if (!beatmapId) return;

        $.ajax({
            type: 'GET',
            url: '/get_tags/',
            data: { 'beatmap_id': beatmapId },
            success: function(tags) {
                // Remove existing tooltips to prevent orphaned descriptions
                $('#beatmap-applied-tags .tooltip, #beatmap-applied-tags .description-author').remove();
                
                // Clear any pending tooltip timeouts
                $('#beatmap-applied-tags').empty().append('Tags: ');

                tags.forEach(function(tag) {
                    // Assign class based on whether the user has applied the tag
                    var tagClass = tag.is_applied_by_user ? 'tag-applied' : 'tag-unapplied';
                    
                    // Append the tag with the appropriate class and data attributes
                    $('#beatmap-applied-tags').append(`
                        <span class="tag ${tagClass}" 
                              data-tag-name="${tag.name}" 
                              data-applied-by-user="${tag.is_applied_by_user}" 
                              data-description="${tag.description || ''}"
                              data-description-author="${tag.description_author || ''}"
                              data-beatmap-id="${beatmapId}">
                            ${tag.name} (${tag.apply_count})
                        </span>
                    `);
                });
            },
            error: function(xhr, status, error) {
                console.error('AJAX error:', status, error);
            }
        });
    }

    // Initial call to load the tags
    refreshTags();

    // NAVBAR FUNCTIONALITY
    // For the nav bar
    // Vanilla JavaScript to toggle the dropdown menu
    var profileMenuButton = document.getElementById('profileMenuButton');
    if (profileMenuButton) {
        profileMenuButton.onclick = function() {
            var dropdown = document.getElementById('profileDropdown');
            dropdown.style.display = (dropdown.style.display === 'block') ? 'none' : 'block';
        };
    }

    // Close the dropdown if the user clicks outside of it
    window.onclick = function(event) {
        if (!event.target.matches('#profileMenuButton')) {
            var dropdowns = document.getElementsByClassName('dropdown-content');
            for (var i = 0; i < dropdowns.length; i++) {
                var openDropdown = dropdowns[i];
                if (openDropdown.style.display === 'block') {
                    openDropdown.style.display = 'none';
                }
            }
        }
    };

    // COLLAPSIBLE PANELS FUNCTIONALITY
    // Initialize collapsible panels
    function initializeCollapsiblePanels() {
        var coll = document.getElementsByClassName('collapsible-description-header');
        for (var i = 0; i < coll.length; i++) {
            coll[i].addEventListener('click', function() {
                var content = document.getElementById(this.getAttribute('aria-controls'));
                var expanded = this.getAttribute('aria-expanded') === 'true';
                this.setAttribute('aria-expanded', !expanded);
                content.setAttribute('aria-hidden', expanded);
            });
        }
    }

    // Call the function to initialize collapsible panels
    initializeCollapsiblePanels();

    // Initialize tooltips using event delegation
    function initializeTooltips() {
        // Event delegation for mouseenter and mouseleave on .tag elements within .applied-tags and .tags-usage
        $(document).on('mouseenter', '.applied-tags .tag, .tags-usage .tag', function() {
            var tag = $(this);
            var description = tag.data('description') || 'No description available.';
            var descriptionAuthor = tag.data('description-author') || '';

            // Set a timeout to show tooltip after 500ms
            var timeout = setTimeout(function() {
                // Check if tooltip already exists
                if (tag.data('tooltip-visible')) return;

                // Create tooltip element
                var $tooltip = $('<div class="tooltip"></div>').text(description).appendTo('body').css({
                    opacity: 0,
                    position: 'absolute'
                });

                // Create description_author element
                var $author = null;
                if(descriptionAuthor) {
                    $author = $('<div class="description-author"></div>').text(descriptionAuthor).appendTo('body').css({
                        opacity: 0,
                        position: 'absolute',
                        pointerEvents: 'none' // Ensure it doesn't block clicks
                    });
                }

                // Position the tooltip above the tag
                var tagOffset = tag.offset();
                var tagWidth = tag.outerWidth();
                var tooltipWidth = $tooltip.outerWidth();
                var tooltipHeight = $tooltip.outerHeight();

                var tooltipLeft = tagOffset.left + (tagWidth / 2) - (tooltipWidth / 2);
                var tooltipTop = tagOffset.top - tooltipHeight - 8; // 8px gap

                // Ensure tooltip doesn't go off the left or right edge
                tooltipLeft = Math.max(tooltipLeft, 10); // 10px from left
                tooltipLeft = Math.min(tooltipLeft, $(window).width() - tooltipWidth - 10); // 10px from right

                $tooltip.css({
                    left: tooltipLeft + 'px',
                    top: tooltipTop + 'px',
                    opacity: '1'
                });

                // Position author if exists
                if ($author) {
                    var tooltipRect = $tooltip[0].getBoundingClientRect(); // Get the tooltip's final rendered position
                    var authorLeft = tooltipRect.left + window.pageXOffset + tooltipRect.width - $author.outerWidth() - 4; // Right corner of tooltip
                    var authorTop = tooltipRect.top + window.pageYOffset + tooltipRect.height - $author.outerHeight() + 2; // Bottom-right corner of tooltip

                    $author.css({
                        left: authorLeft + 'px',
                        top: authorTop + 'px',
                        opacity: '1'
                    });
                }

                // Store tooltip references
                tag.data('tooltip-visible', true);
                tag.data('tooltip-element', $tooltip);
                if ($author) {
                    tag.data('author-element', $author);
                }
            }, 500); // 500ms delay

            // Store the timeout so it can be cleared on mouseleave
            tag.data('tooltip-timeout', timeout);
        }).on('mouseleave', '.applied-tags .tag, .tags-usage .tag', function() {
            var tag = $(this);
            var timeout = tag.data('tooltip-timeout');

            // Clear the timeout if tooltip hasn't been shown yet
            if (timeout) {
                clearTimeout(timeout);
                tag.removeData('tooltip-timeout');
            }

            // If tooltip is visible, fade it out and remove
            if (tag.data('tooltip-visible')) {
                var $tooltip = tag.data('tooltip-element');
                var $author = tag.data('author-element');

                if ($tooltip) {
                    $tooltip.css('opacity', '0');
                    setTimeout(function() {
                        $tooltip.remove();
                        tag.removeData('tooltip-element');
                    }, 300); // Match CSS transition duration
                }

                if ($author) {
                    $author.css('opacity', '0');
                    setTimeout(function() {
                        $author.remove();
                        tag.removeData('author-element');
                    }, 300);
                }

                tag.removeData('tooltip-visible');
            }
        });
    }

    // Initialize tooltips on page load
    initializeTooltips();

    // Function to load tags on page load (e.g., Top Tags)
    function loadInitialTags() {
    }

    // Call the function to attach hover events to initial Top Tags
    loadInitialTags();

    // -----------------------------------------------
    // Load More functionality for Recommended Maps
    // -----------------------------------------------

    // Initialize recommendationsOffset based on the current number of maps displayed
    let recommendationsOffset = $('#recommended-map-list .map-entry').length;

    $('#load-more-btn').on('click', function() {
        $.ajax({
            type: 'GET',
            url: '/load_more_recommendations/',
            data: {
                'offset': recommendationsOffset,
                'limit': 5
            },
            success: function(response) {
                if (response.rendered_maps.trim() === '') {
                    // No more maps to load
                    $('#load-more-btn').text('No more recommendations').prop('disabled', true);
                } else {
                    // Append the new maps to the list
                    $('#recommended-map-list').append(response.rendered_maps);
                    recommendationsOffset += 5;
                }
            },
            error: function(xhr, status, error) {
                console.error('Error loading more recommendations:', error);
            }
        });
    });

}); 


// Search_results star rating slider
$(function() {
    // Initialize the star rating slider
    $("#star-rating-slider").slider({
        range: true,
        min: 0,
        max: 10,
        step: 0.1,
        values: [
            parseFloat($("#star_min").val()) || 0,
            parseFloat($("#star_max").val()) >= 10 ? 10 : parseFloat($("#star_max").val()) || 10
        ],
        slide: function(event, ui) {
            $("#star_min").val(ui.values[0]);
            if (ui.values[1] >= 10) {
                $("#star_max").val(10); // Keep star_max at 10 to indicate "10+"
                $("#star-rating-max").text("10+");
            } else {
                $("#star_max").val(ui.values[1]);
                $("#star-rating-max").text(ui.values[1].toFixed(1));
            }
            $("#star-rating-min").text(ui.values[0].toFixed(1));
        },
        change: function(event, ui) {
            var min = parseFloat($("#star_min").val()) || 0;
            var max = parseFloat($("#star_max").val()) || 10;

            if (max >= 10) {
                $("#star-rating-max").text("10+");
            } else {
                $("#star-rating-max").text(max.toFixed(1));
            }

            $("#star-rating-min").text(min.toFixed(1));
        }
    });

    // Set initial slider labels
    var initial_min = parseFloat($("#star_min").val());
    var initial_max = parseFloat($("#star_max").val());

    if (initial_max >= 10) {
        $("#star-rating-max").text("10+");
    } else {
        $("#star-rating-max").text(isNaN(initial_max) ? "10+" : initial_max.toFixed(1));
    }

    if (!isNaN(initial_min)) {
        $("#star-rating-min").text(initial_min.toFixed(1));
    } else {
        $("#star-rating-min").text("0.0");
    }

    // Optional: Update labels if user manually changes hidden inputs
    $("#star_min, #star_max").on('change', function() {
        var min = parseFloat($("#star_min").val()) || 0;
        var max = parseFloat($("#star_max").val()) || 10;

        if (max >= 10) {
            $("#star-rating-max").text("10+");
        } else {
            $("#star-rating-max").text(max.toFixed(1));
        }

        $("#star-rating-min").text(min.toFixed(1));
        $("#star-rating-slider").slider("values", [min, max >= 10 ? 10 : max]);
    });
});
