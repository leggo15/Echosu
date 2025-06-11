# echosu/views/misc.py

# Django imports
from django.shortcuts import render, redirect
from django.db.models import Count

# Local application imports
from ..models import Tag

# ----------------------------- Miscellaneous Views ----------------------------- #

def about(request):
    """Render the about page."""
    return render(request, 'about.html')

def admin_redirect(request):
    """Redirect to the admin panel."""
    return redirect('/admin/')

def error_page_view(request):
    """Render the error_page template."""
    return render(request, 'error_page.html')

def tag_library(request):
    """Displays a list of all tags, ordered alphabetically."""
    tags = Tag.objects.annotate(beatmap_count=Count('beatmaps')).order_by('name')
    context = {'tags': tags}
    return render(request, 'tag_library.html', context)

def custom_404_view(request, exception):
    """Custom view for handling 404 Not Found errors."""
    return render(request, '404.html', {}, status=404)
