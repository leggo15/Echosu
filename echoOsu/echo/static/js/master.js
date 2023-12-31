$(document).ready(function() {
    var selectedTag;

    $('#tag-input').on('input', function() {
        var inputVal = $(this).val();
        console.log('Input value:', inputVal); // Diagnostic log
        if (inputVal.length > 0) {
            $.ajax({
                url: '/echo/search_tags/',
                data: { 'q': inputVal },
                success: function(data) {
                    console.log('Data received:', data); // Diagnostic log
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

    $('#tag-list').on('click', 'li', function() {
        selectedTag = $(this).text().split(' (')[0];
        console.log('Selected tag:', selectedTag); // Diagnostic log
        $('#tag-input').val(selectedTag);
        $('#tag-list').empty();
    });

    $('.apply-tag-btn').on('click', function() {
        var tagName = $('#tag-input').val();
        if (tagName) {
            applyTag(tagName);
        } else {
            alert('Please enter a tag name.');
        }
    });

    // Handle clicking on a tag to toggle it
    $('.applied-tags').on('click', '.tag', function() {
        var $tag = $(this);
        var tagName = $tag.data('tag-name');
        var isAppliedByUser = $tag.data('applied-by-user') === 'true'; // Ensure to compare with string 'true'

        // Toggle the tag based on whether it's applied by the user
        if (isAppliedByUser) {
            removeTag(tagName, $tag);
        } else {
            applyTag(tagName);
        }
    });

    // Initial call to load the tags
    refreshTags();
});

function applyTag(tagName) {
    var beatmapId = $('#current_beatmap_id').val();
    $.ajax({
        type: 'POST',
        url: '/echo/apply_tag/',
        data: {
            'tag': tagName,
            'beatmap_id': beatmapId,
            'csrfmiddlewaretoken': $('input[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            if (response.status === 'success') {
                refreshTags();
            }
        },
        error: function(xhr, status, error) {
            console.error('AJAX error:', status, error);
        }
    });
}

function removeTag(tagName, $tagElement) {
    var beatmapId = $('#current_beatmap_id').val();
    $.ajax({
        type: 'POST',
        url: '/echo/remove_tag/',
        data: {
            'tag': tagName,
            'beatmap_id': beatmapId,
            'csrfmiddlewaretoken': $('input[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            if (response.status === 'success') {
                refreshTags();
            }
        },
        error: function(xhr, status, error) {
            console.error('AJAX error:', status, error);
        }
    });
}

function refreshTags() {
    var beatmapId = $('#current_beatmap_id').val();
    $.ajax({
        type: 'GET',
        url: '/echo/get_tags/',
        data: { 'beatmap_id': beatmapId },
        success: function(tags) {
            $('.applied-tags').empty().append('Tags: ');
            tags.forEach(function(tag) {
                $('.applied-tags').append(`<span class="tag" data-tag-name="${tag.name}" data-applied-by-user="${tag.is_applied_by_user}">${tag.name} (${tag.apply_count})</span>`);
            });
        },
        error: function(xhr, status, error) {
            console.error('AJAX error:', status, error);
        }
    });
}
