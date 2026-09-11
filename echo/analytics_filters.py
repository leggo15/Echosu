"""Conservative filtering for analytics only; public pages stay crawlable."""

from functools import wraps
import re
from uuid import UUID

from django.http import JsonResponse
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, Value, When


# Match identifiable automated clients, not generic words such as "bot" inside
# device names (for example, Cubot phones). A normal browser UA is not proof of a human.
AUTOMATED_USER_AGENT = re.compile(
    r'googlebot|google-inspectiontool|googleother|adsbot-google|mediapartners-google|'
    r'bingbot|bingpreview|msnbot|duckduckbot|applebot|yandexbot|yandeximages|'
    r'baiduspider|bytespider|petalbot|amazonbot|yahoo! slurp|'
    r'ahrefsbot|semrushbot|mj12bot|dotbot|blexbot|dataforseobot|'
    r'gptbot|oai-searchbot|chatgpt-user|claudebot|claude-searchbot|claude-user|'
    r'perplexitybot|perplexity-user|ccbot|cohere-ai|'
    r'facebookexternalhit|meta-externalagent|meta-externalfetcher|'
    r'twitterbot|discordbot|slackbot|telegrambot|linkedinbot|pinterestbot|'
    r'headlesschrome|phantomjs|lighthouse|pagespeed|'
    r'python-requests|python-urllib|aiohttp|httpx/|scrapy|curl/|wget/|'
    r'go-http-client|apache-httpclient|okhttp/|node-fetch|undici|'
    r'uptimerobot|pingdom|statuscake|'
    r'(?<![a-z])(?:bot|crawler|spider)(?![a-z])',
    re.IGNORECASE,
)


def is_automated_user_agent(user_agent):
    return bool(AUTOMATED_USER_AGENT.search(user_agent or ''))


def analytics_client_id(request):
    """Only accept the UUID format issued by our first-party analytics cookie."""
    raw = request.COOKIES.get('analytics_id')
    if not isinstance(raw, str) or len(raw) != 36:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def filter_analytics(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if is_automated_user_agent(request.headers.get('User-Agent')):
            return JsonResponse({'ok': False, 'ignored': True})
        # Cookie-less anonymous traffic cannot provide a stable visitor identity.
        # Logged-in users can still be counted by their existing account hash.
        authenticated = getattr(getattr(request, 'user', None), 'is_authenticated', False)
        if not authenticated and not analytics_client_id(request):
            return JsonResponse({'ok': False, 'ignored': True})
        return view(request, *args, **kwargs)

    return wrapped


def include_likely_bots(request):
    return request.GET.get('include_likely_bots') == '1'


def admin_analytics_events(model, *, include_bots=False):
    """Classify anonymous one-interaction browsers using their entire stored history.

    Compute this at read time so old events and new activity follow the same rule.
    Capped, indexed existence checks avoid counting a prolific client's entire
    history for each event. Automatic impressions do not establish engagement.
    """
    from .models import AnalyticsClickEvent, AnalyticsSearchEvent

    searches = AnalyticsSearchEvent.objects.filter(client_id=OuterRef('client_id'))
    clicks = AnalyticsClickEvent.objects.filter(client_id=OuterRef('client_id')).exclude(action='impression')
    multiple_interactions = (
        Exists(searches[1:2]) | Exists(clicks[1:2]) | (Exists(searches) & Exists(clicks))
    )
    anonymous = (Q(logged_in_user_id__isnull=True) | Q(logged_in_user_id='')) & Q(is_staff=False)
    # Missing identifiers cannot be linked to other visits; do not pool them into
    # one apparently active browser. Logged-in events always remain included.
    missing_identity = Q(client_id__isnull=True) | Q(client_id='')
    events = model.objects.annotate(is_likely_bot=Case(
        When(anonymous & (missing_identity | ~multiple_interactions), then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    ))
    return events if include_bots else events.filter(is_likely_bot=False)
