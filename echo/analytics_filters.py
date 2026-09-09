"""Conservative filtering for analytics only; public pages stay crawlable."""

from functools import wraps
import re
from uuid import UUID

from django.http import JsonResponse


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
