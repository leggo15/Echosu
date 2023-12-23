$(function() {
    // Fetch tag suggestions
    $("#tag-input").on("input", function() {
        var input = $(this).val();
        if(input.length > 2) {
            $.ajax({
                url: '/tag_suggestions/', // URL to your Django view that returns tag suggestions
                data: { 'term': input },
                dataType: 'json',
                success: function(data) {
                    var list = $("#tag-list");
                    list.empty();
                    $.each(data, function(i, val) {
                        $("<li></li>").text(val).appendTo(list);
                    });
                }
            });
        }
    });

    // Add a tag to the beatmap
    $("#tag-list").on("click", "li", function() {
        var tag = $(this).text();
        var beatmapId = $('#current_beatmap_id').val(); // The hidden input field containing the current beatmap ID
    
        // AJAX call to add the tag to the beatmap
        $.ajax({
            url: '/add_tag_to_beatmap/', // URL to your Django view that adds a tag
            type: 'POST',
            data: {
                'tag': tag,
                'beatmap_id': beatmapId,
               // 'csrfmiddlewaretoken': $('input[name=csrfmiddlewaretoken]').val() // Include CSRF token
            },
            success: function(response) {
                if (response.status === 'tag-created') {
                    alert("New tag created and added successfully");
                } else {
                    alert("Tag added successfully");
                }
            },
            error: function(xhr, status, error) {
                // Handle any errors
                alert("Error adding tag");
            }
        });
    });    
});


