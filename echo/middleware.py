from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token as DRFToken
from .models import APIRequestLog, CustomToken
from django.conf import settings
import uuid
import hashlib

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
