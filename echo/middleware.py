from django.utils.deprecation import MiddlewareMixin
from django.urls import resolve
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token
from .models import APIRequestLog, CustomToken
import hashlib

class APILoggingMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Check if the request is to an API endpoint
        if request.path.startswith('/api/'):
            # Get the user from the token
            auth_header = request.headers.get('Authorization', '')
            user = None
            if auth_header.startswith('Token '):
                    raw_token = auth_header.split(' ')[1]
                    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
                    try:
                        token = CustomToken.objects.get(key=hashed_token)
                        user = token.user
                    except CustomToken.DoesNotExist:
                        user = AnonymousUser()
            else:
                user = AnonymousUser()


            # Log detailed request
            try:
                APIRequestLog.objects.create(
                    user=user if getattr(user, 'is_authenticated', False) else None,
                    method=request.method,
                    path=request.path,
                )
            except Exception:
                pass
        return None
