from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import CustomToken
import hashlib

class CustomTokenAuthentication(BaseAuthentication):
    keyword = 'Token'

    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith(self.keyword):
            return None

        raw_token = auth_header.split()[1]
        hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()

        try:
            token = CustomToken.objects.get(key=hashed_token)
        except CustomToken.DoesNotExist:
            raise AuthenticationFailed('Invalid token')

        return (token.user, token)