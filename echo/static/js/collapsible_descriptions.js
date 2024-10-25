$(document).ready(function(){
    // Function to toggle the collapsible content
    function toggleCollapsible(header) {
        header.toggleClass('active');
        header.find('.arrow').toggleClass('rotated');
        header.next('.collapsible-description-content').toggleClass('show');

        // Update ARIA attributes
        const isExpanded = header.hasClass('active');
        header.attr('aria-expanded', isExpanded);
        header.next('.collapsible-description-content').attr('aria-hidden', !isExpanded);
    }

    // Click event
    $('.collapsible-description-header').click(function(){
        toggleCollapsible($(this));
    });

    // Keyboard event
    $('.collapsible-description-header').keydown(function(e){
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault(); // Prevent scrolling when space is pressed
            toggleCollapsible($(this));
        }
    });
});