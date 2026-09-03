# echosu/views/misc.py


# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.conf import settings
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Tag


# ----------------------------- pages ----------------------------- #

GOOGLE_SITE_VERIFICATION_FILE = "google6293f4a951499d4d.html"


def google_site_verification(request):
    verification_path = settings.BASE_DIR / GOOGLE_SITE_VERIFICATION_FILE
    return HttpResponse(verification_path.read_bytes(), content_type="text/html")


def error_page_view(request):
    return render(request, 'error_page.html')

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
