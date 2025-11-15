from pathlib import Path
import os
import json
from dotenv import load_dotenv

# "/home/ubuntu/Echosu/.env"

# Define the base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

SECRET_KEY = os.getenv('SECRET_KEY')

# Read DEBUG from env: set DEBUG=1 / true to enable
def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

DEBUG = _get_bool('DEBUG', default=True)

DEBUG_PORT = int(os.getenv('DEBUG_PORT', '8000'))
BASE_URL = f"127.0.0.1" if DEBUG else "echosu.com"

# Allow override via .env (JSON list or comma-separated)
_allowed_hosts_env = os.getenv('ALLOWED_HOSTS')
def _parse_allowed_hosts(raw: str):
    s = (raw or '').strip()
    if not s:
        return []
    # Strip wrapping quotes
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1].strip()
    # Try JSON first
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return [str(h).strip().strip('"\'') for h in val if str(h).strip()]
        if isinstance(val, str):
            return [val.strip()]
    except Exception:
        pass
    # Fallback: comma-separated; strip brackets/quotes
    s = s.strip('[]')
    return [p.strip().strip('"\'') for p in s.split(',') if p.strip()]

if _allowed_hosts_env:
    ALLOWED_HOSTS = _parse_allowed_hosts(_allowed_hosts_env)
else:
    ALLOWED_HOSTS = [BASE_URL, f"www.{BASE_URL}"]

# Ensure dev hosts are allowed when in DEBUG to avoid DisallowedHost during local work
if DEBUG:
    dev_hosts = {'127.0.0.1', 'localhost', '[::1]', 'testserver'}
    ALLOWED_HOSTS = list(set(ALLOWED_HOSTS or []) | dev_hosts)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'echo',
    'storages',
    'rest_framework',
    'rest_framework.authtoken',
    
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'echo.middleware.APILoggingMiddleware',
    'echo.middleware.AnonymousAnalyticsMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

ROOT_URLCONF = 'echoOsu.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'echo.context_processors.add_user_profile_to_context',
                'echo.context_processors.osu_oauth_url',
            ],
        },
    },
]


WSGI_APPLICATION = 'echoOsu.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'CONN_MAX_AGE': 60,
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Osu API Credentials
SOCIAL_AUTH_OSU_KEY = os.getenv('SOCIAL_AUTH_OSU_KEY')
SOCIAL_AUTH_OSU_SECRET = os.getenv('SOCIAL_AUTH_OSU_SECRET')
SOCIAL_AUTH_OSU_REDIRECT_URI = f"http://{BASE_URL}:{DEBUG_PORT}/callback" if DEBUG \
        else f"https://www.{BASE_URL}/callback"


AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

# AWS S3 Configuration
AWS_STORAGE_BUCKET_NAME = 'echosu-s3-v2'
AWS_S3_REGION_NAME = 'eu-central-1'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com'

AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False  # This setting is important for public access


# Media files (User uploaded content)
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'

# Storage backends
STORAGES = {
    'default': {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        'OPTIONS': {
            'location': 'media',
        },
    },
    'staticfiles': {
        'BACKEND': 'storages.backends.s3boto3.S3StaticStorage',
        'OPTIONS': {
            'location': 'static',  # Stores static files under 'static' prefix in the bucket
        },
    },
}



# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/
STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'

# Directory where collectstatic will collect static files for deployment
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Additional directories to include in static files search
STATICFILES_DIRS = [
    BASE_DIR / 'echo' / 'static',
]


# Authentication
LOGIN_URL = 'login'
LOGOUT_URL = 'logout'
LOGIN_REDIRECT_URL = '/'


########################### API ###########################

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'echo.authentication.CustomTokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# admin provisioning via env (comma-separated osu IDs)
ADMIN_OSU_IDS = os.getenv('ADMIN_OSU_IDS', '')

# Security flags (env-driven; default cookies secure in prod)
SESSION_COOKIE_SECURE = _get_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = _get_bool('CSRF_COOKIE_SECURE', not DEBUG)

X_FRAME_OPTIONS = os.getenv('X_FRAME_OPTIONS', 'DENY')
SECURE_REFERRER_POLICY = os.getenv('SECURE_REFERRER_POLICY', 'strict-origin-when-cross-origin')

# CSRF trusted origins (JSON list or comma-separated)
_csrf_origins = os.getenv('CSRF_TRUSTED_ORIGINS')
if _csrf_origins:
    try:
        CSRF_TRUSTED_ORIGINS = json.loads(_csrf_origins) if _csrf_origins.strip().startswith('[') \
            else [o.strip() for o in _csrf_origins.split(',') if o.strip()]
    except Exception:
        CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]
