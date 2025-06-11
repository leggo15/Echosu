# echosu/views/misc.py


# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.db.models import Count
from django.shortcuts import redirect, render

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Tag


# ----------------------------- pages ----------------------------- #

def about(request):
    return render(request, 'about.html')


def admin_redirect(request):
    return redirect('/admin/')


def error_page_view(request):
    return render(request, 'error_page.html')


def tag_library(request):
    tags = Tag.objects.annotate(beatmap_count=Count('beatmaps')).order_by('name')
    return render(request, 'tag_library.html', {'tags': tags})


def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
