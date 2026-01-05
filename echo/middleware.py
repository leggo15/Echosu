from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token as DRFToken
from .models import APIRequestLog, CustomToken, HourlyActiveUserCount
from django.conf import settings
import uuid
import hashlib
from django.core.cache import cache
from django.utils import timezone
from django.db.models import F

class APILoggingMiddleware(MiddlewareMixin):
    def _resolve_user_from_authorization(self, request):
        auth_header = request.headers.get('Authorization', '') or ''
        if not auth_header.startswith('Token '):
            return AnonymousUser()

        # Try custom hashed token first
        try:
            raw_token = auth_header.split(' ')[1]
        except Exception:
            return AnonymousUser()

        try:
            hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
            token = CustomToken.objects.get(key=hashed_token)
            return token.user
        except CustomToken.DoesNotExist:
            # Fallback to DRF token (plain key)
            try:
                drf_token = DRFToken.objects.get(key=raw_token)
                return drf_token.user
            except Exception:
                return AnonymousUser()

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Defer logging to process_response to capture status_code, but resolve user early
        if request.path.startswith('/api/'):
            request._api_user_for_logging = self._resolve_user_from_authorization(request)
        return None

    def process_response(self, request, response):
        try:
            if getattr(request, 'path', '').startswith('/api/'):
                user = getattr(request, '_api_user_for_logging', AnonymousUser())
                # Only log when a real authenticated user is attached
                if getattr(user, 'is_authenticated', False):
                    APIRequestLog.objects.create(
                        user=user,
                        method=getattr(request, 'method', 'GET'),
                        path=getattr(request, 'path', ''),
                        status_code=getattr(response, 'status_code', None),
                    )
        except Exception:
            pass
        return response


class AnonymousAnalyticsMiddleware(MiddlewareMixin):
    """
    Ensures a pseudonymous analytics cookie is present for anonymous usage tracking.
    - Cookie value is a random UUID not linked to any account.
    - Used only to estimate unique users; no PII stored.
    """
    COOKIE_NAME = 'analytics_id'
    MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days

    def process_response(self, request, response):
        try:
            if self.COOKIE_NAME not in request.COOKIES:
                cid = str(uuid.uuid4())
                secure = not getattr(settings, 'DEBUG', False)
                response.set_cookie(
                    self.COOKIE_NAME,
                    cid,
                    max_age=self.MAX_AGE_SECONDS,
                    samesite='Lax',
                    secure=secure,
                    httponly=False,
                    )
        except Exception:
            pass
        return response


class HourlyActiveUserCountMiddleware(MiddlewareMixin):
    """
    Track hourly active authenticated users WITHOUT persisting identities.

    Mechanism:
    - For each authenticated request, we `cache.add()` a key for (hour, user_id).
      This keeps uniqueness without writing user ids to DB.
    - If the key is new, we increment HourlyActiveUserCount(hour).count.
    """
    CACHE_TTL_SECONDS = 60 * 60 * 30  # 30h; covers late events + clock drift

    @staticmethod
    def _hour_floor(dt):
        try:
            return dt.replace(minute=0, second=0, microsecond=0, tzinfo=dt.tzinfo)
        except Exception:
            return dt

    def process_request(self, request):
        try:
            user = getattr(request, 'user', None)
            if not getattr(user, 'is_authenticated', False):
                return None
            uid = getattr(user, 'id', None)
            if not uid:
                return None
            hour = self._hour_floor(timezone.now())
            key = f"hau:{int(hour.timestamp())}:{int(uid)}"
            first_seen = False
            try:
                first_seen = bool(cache.add(key, 1, timeout=self.CACHE_TTL_SECONDS))
            except Exception:
                first_seen = False
            if not first_seen:
                return None
            obj, created = HourlyActiveUserCount.objects.get_or_create(hour=hour, defaults={'count': 1})
            if not created:
                HourlyActiveUserCount.objects.filter(pk=obj.pk).update(count=F('count') + 1)
        except Exception:
            pass
        return None
