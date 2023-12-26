$(document).ready(function() {
    var selectedTag;

    $('#tag-input').on('input', function() {
        var inputVal = $(this).val();
        console.log('Input value:', inputVal); // Diagnostic log
        if(inputVal.length > 0){
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
        console.log('Apply Tag button clicked'); // Diagnostic log
        var tagName = $('#tag-input').val();
        if (tagName) {
            applyTag(tagName);
        } else {
            alert('Please enter a tag name.');
        }
    });
});

function applyTag(tagName) {
    console.log('Applying tag:', tagName); // Diagnostic log
    var beatmapId = $('#current_beatmap_id').val();
    console.log('Beatmap ID:', beatmapId); // Diagnostic log
    $.ajax({
        type: 'POST',
        url: '/echo/apply_tag/',
        data: {
            'tag': tagName,
            'beatmap_id': beatmapId,
            'csrfmiddlewaretoken': $('input[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            console.log('Response from server:', response); // Diagnostic log
            if (response.status === 'success') {
                $('#tag-input').val('');
                alert('Tag applied successfully!');
            }
        },
        error: function(xhr, status, error) {
            console.error('AJAX error:', status, error); // Diagnostic log
        }
    });
}
