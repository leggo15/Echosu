from django.utils.deprecation import MiddlewareMixin
from django.urls import resolve
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token
from .models import APIRequestLog, CustomToken
import hashlib

class APILoggingMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path.startswith('/api/'):
            auth_header = request.headers.get('Authorization', '')
            user = AnonymousUser()
            if auth_header.startswith('Token '):
                raw_token = auth_header.split(' ')[1]
                hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
                try:
                    token = CustomToken.objects.get(key=hashed_token)
                    user = token.user
                except CustomToken.DoesNotExist:
                    pass  # Keep user as AnonymousUser

            if isinstance(user, AnonymousUser):
                return None  # Ignore unauthorized requests

            # Log the API request
            APIRequestLog.objects.create(
                user=user,
                method=request.method,
                path=request.path,
                # Exclude remote_addr if not needed
            )
        return None
