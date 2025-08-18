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

def error_page_view(request):
    return render(request, 'error_page.html')

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
