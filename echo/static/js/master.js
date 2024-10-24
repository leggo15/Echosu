
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
            modifyTag(tagName, beatmapId, 'apply');
        } else {
            alert('Please enter a tag name.');
        }
    });

    // Applied tags click (for applying/removing tags)
    function attachTagClickEvents() {
        $('.applied-tags').off('click', '.tag').on('click', '.tag', function() {
            var $this = $(this);
            var tagName = $this.data('tag-name');
            var beatmapId = $('#current_beatmap_id').val();
            var action = $this.attr('data-applied-by-user') === 'true' ? 'remove' : 'apply';
            modifyTag(tagName, beatmapId, action);
        });
    }

    // Modify tag function
    function modifyTag(tagName, beatmapId, action) {
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
                refreshTags();
            },
            error: function(xhr, status, error) {
                console.error('AJAX error:', status, error, xhr.responseText);
            }
        });
    }

    // Refresh tags
    function refreshTags() {
        var beatmapId = $('#current_beatmap_id').val();
        $.ajax({
            type: 'GET',
            url: '/get_tags/',
            data: { 'beatmap_id': beatmapId },
            success: function(tags) {
                $('.applied-tags').empty().append('Tags: ');
                tags.forEach(function(tag) {
                    // Assign class based on whether the user has applied the tag
                    var tagClass = tag.is_applied_by_user ? 'tag-applied' : 'tag-unapplied';
                    
                    // Append the tag with the appropriate class and data attributes
                    $('.applied-tags').append(`
                        <span class="tag ${tagClass}" 
                                data-tag-name="${tag.name}" 
                                data-applied-by-user="${tag.is_applied_by_user}" 
                                data-description=' "${tag.description || ''}" '
                                data-description-author=" - ${tag.description_author || ''}">
                            ${tag.name} (${tag.apply_count})
                        </span>
                    `);
                });
                attachTagClickEvents(); // Re-attach click events to new tags
                // No need to call attachHoverEvents here
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
    document.getElementById('profileMenuButton').onclick = function() {
        var dropdown = document.getElementById('profileDropdown');
        dropdown.style.display = (dropdown.style.display === 'block') ? 'none' : 'block';
    };

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

    // COLLAPSIBLE API KEYS FUNCTIONALITY
    // Initialize collapsible panels
    function initializeCollapsiblePanels() {
        var coll = document.getElementsByClassName('collapsible');
        for (var i = 0; i < coll.length; i++) {
            coll[i].addEventListener('click', function() {
                this.classList.toggle('active');
                var content = this.nextElementSibling;
                if (content.style.maxHeight){
                    content.style.maxHeight = null;
                } else {
                    content.style.maxHeight = content.scrollHeight + "px";
                } 
            });
        }
    }

    // Call the function to initialize collapsible panels
    function initializeTooltips() {
        // Event delegation for mouseenter and mouseleave on .tag elements within .applied-tags and .tags-usage
        $('.applied-tags, .tags-usage').on('mouseenter', '.tag', function() {
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
        }).on('mouseleave', '.tag', function() {
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
        $('.tags-usage .tag').each(function() {
            // No need to attach hover events individually since we're using event delegation
            // This function can be used for other initial setups if needed
        });
    }

    // Call the function to attach hover events to initial Top Tags
    loadInitialTags();
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


// For collapsible items in home and search
$(document).ready(function(){
    // Toggle the collapsible content when header is clicked
    $('.collapsible-header').click(function(){
        $(this).toggleClass('active');
        $(this).find('.arrow').toggleClass('rotated');
        $(this).next('.collapsible-content').toggleClass('show');
    });
});