$(document).ready(function() {
    var selectedTag;

    // Tag input functionality
    $('#tag-input').on('input', function() {
        var inputVal = $(this).val();
        if (inputVal.length > 0) {
            $.ajax({
                url: '/echo/search_tags/',
                data: { 'q': inputVal },
                success: function(data) {
                    $('#tag-list').empty();
                    data.forEach(function(tag) {
                        $('#tag-list').append(`<li>${tag.name} (${tag.beatmap_count})</li>`);
                    });
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
            url: '/echo/modify_tag/',
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
            url: '/echo/get_tags/',
            data: { 'beatmap_id': beatmapId },
            success: function(tags) {
                $('.applied-tags').empty().append('Tags: ');
                tags.forEach(function(tag) {
                    // Assign class based on whether the user has applied the tag
                    var tagClass = tag.is_applied_by_user ? 'tag-applied' : 'tag-unapplied';
                    
                    // Append the tag with the appropriate class
                    $('.applied-tags').append(`
                        <span class="tag ${tagClass}" 
                              data-tag-name="${tag.name}" 
                              data-applied-by-user="${tag.is_applied_by_user}" 
                              data-description="${tag.description}">
                            ${tag.name} (${tag.apply_count})
                        </span>
                    `);
                });
                attachTagClickEvents(); // Re-attach click events to new tags
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
    initializeCollapsiblePanels();

});

// Tag description
document.addEventListener('DOMContentLoaded', function () {
    const tags = document.querySelectorAll('.tag');

    tags.forEach(function(tag) {
        let timeout;

        tag.addEventListener('mouseenter', function() {
            // Start the timeout to show the tooltip after 500ms
            timeout = setTimeout(function() {
                // Check if tooltip already exists to prevent duplicates
                if (tag._tooltip) return;

                // Create tooltip element
                let tooltip = document.createElement('div');
                tooltip.className = 'tooltip';
                tooltip.innerText = tag.getAttribute('data-description');
                tooltip.style.opacity = '0';
                document.body.appendChild(tooltip);

                // Create description_author element
                let descriptionAuthor = document.createElement('div');
                descriptionAuthor.className = 'description-author';
                descriptionAuthor.innerText = tag.getAttribute('data-description-author');
                descriptionAuthor.style.opacity = '0';
                descriptionAuthor.style.pointerEvents = 'none'; // Ensure it doesn't block clicks
                document.body.appendChild(descriptionAuthor);

                // Attach elements to tag
                tag._tooltip = tooltip;
                tag._descriptionAuthor = descriptionAuthor;

                // Now that elements are added to the DOM, wait for the next frame
                requestAnimationFrame(() => {
                    // Get dimensions after elements are rendered
                    let rect = tag.getBoundingClientRect();
                    let tooltipRect = tooltip.getBoundingClientRect();
                    let authorRect = descriptionAuthor.getBoundingClientRect();

                    // Position tooltip above the tag
                    tooltip.style.left = (rect.left + window.pageXOffset + (rect.width / 2) - (tooltipRect.width / 2)) + 'px';
                    tooltip.style.top = (rect.top + window.pageYOffset - tooltipRect.height - 8) + 'px'; // 8px gap

                    // Position descriptionAuthor overlapping halfway over the tag
                    descriptionAuthor.style.left = (rect.left + window.pageXOffset + (rect.width / 2) - (authorRect.width / 2)) + 'px';
                    descriptionAuthor.style.top = (rect.top + window.pageYOffset + (rect.height / 2) - (authorRect.height / 2)) + 'px';

                    // Fade-in effect
                    tooltip.style.opacity = '1';
                    descriptionAuthor.style.opacity = '1';
                });
            }, 500); // 500ms delay
        });

        tag.addEventListener('mouseleave', function() {
            // Clear the timeout if the user leaves before 500ms
            clearTimeout(timeout);

            if (tag._tooltip) {
                let tooltip = tag._tooltip;

                // Fade-out effect
                tooltip.style.opacity = '0';

                // Remove the tooltip after the transition duration (100ms)
                setTimeout(function() {
                    if (tooltip.parentElement) {
                        tooltip.parentElement.removeChild(tooltip);
                    }
                    tag._tooltip = null;
                }, 100); // Match this with the CSS transition duration
            }

            if (tag._descriptionAuthor) {
                let descriptionAuthor = tag._descriptionAuthor;

                // Fade-out effect
                descriptionAuthor.style.opacity = '0';

                // Remove the descriptionAuthor after the transition duration
                setTimeout(function() {
                    if (descriptionAuthor.parentElement) {
                        descriptionAuthor.parentElement.removeChild(descriptionAuthor);
                    }
                    tag._descriptionAuthor = null;
                }, 100);
            }
        });
    });
});


// Function to apply a tag
function applyTag(tagName) {
    // Check if the tag exists
    $.ajax({
        url: '/check-tag/',
        method: 'GET',
        data: { tag_name: tagName },
        success: function(data) {
            if (data.exists) {
                // Tag exists, proceed to apply it
                submitTag(tagName);
            } else {
                // Tag doesn't exist, prompt for description
                promptForTagDescription(tagName);
            }
        }
    });
}


function modifyTag(tagName) {
    const beatmapId = $('#current_beatmap_id').val();
    const csrfToken = '{{ csrf_token }}';

    $.ajax({
        url: '/echo/modify_tag/',
        method: 'POST',
        data: {
            tag: tagName,
            beatmap_id: beatmapId,
            csrfmiddlewaretoken: csrfToken
        },
        success: function(response) {
            if (response.status === 'needs_description') {
                // Prompt the user for a description
                const description = prompt(`The tag "${tagName}" is new. Please provide a description:`);
                if (description !== null) {
                    // Resend the request with the description
                    $.ajax({
                        url: '/echo/modify_tag/',
                        method: 'POST',
                        data: {
                            tag: tagName,
                            beatmap_id: beatmapId,
                            description: description,
                            csrfmiddlewaretoken: csrfToken
                        },
                        success: function(res) {
                            if (res.status === 'success') {
                                // Update the UI accordingly
                                // For example, refresh the tag list
                                loadTags();
                            } else {
                                alert(res.message);
                            }
                        },
                        error: function(err) {
                            alert('An error occurred. Please try again.');
                        }
                    });
                }
            } else if (response.status === 'success') {
                // Update the UI accordingly
                // For example, refresh the tag list
                loadTags();
            } else {
                alert(response.message);
            }
        },
        error: function(err) {
            alert('An error occurred. Please try again.');
        }
    });
}
