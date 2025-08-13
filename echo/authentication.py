from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import CustomToken
import hashlib
try:
    from rest_framework.authtoken.models import Token as DRFToken
except Exception:  # pragma: no cover
    DRFToken = None

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
            # Fallback to DRF Token if present
            if DRFToken is not None:
                try:
                    drf_token = DRFToken.objects.get(key=raw_token)
                    return (drf_token.user, drf_token)
                except Exception:
                    pass
            raise AuthenticationFailed('Invalid token')

        return (token.user, token)