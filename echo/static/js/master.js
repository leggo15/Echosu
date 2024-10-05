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
                $('.applied-tags').empty().append('Genres: ');
                tags.forEach(function(tag) {
                    var tagClass = tag.is_applied_by_user === 'true' ? 'tag-applied' : 'tag-unapplied';
                    $('.applied-tags').append(`<span class="tag ${tagClass}" data-tag-name="${tag.name}" data-applied-by-user="${tag.is_applied_by_user}">${tag.name} (${tag.apply_count})</span>`);
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
