# echosu/views/auth.py
"""Authentication helpers and OAuth callbacks.

Only import order and layout have been tidied—no code logic has been
modified. Duplicate in-function imports were hoisted to the top of the
file, and import groups follow the *standard-library → third-party →
Django → DRF → local* convention.
"""

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import logging
import time

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
import requests
from ossapi import Ossapi

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

# ---------------------------------------------------------------------------
# Django REST framework imports
# ---------------------------------------------------------------------------
from rest_framework.authtoken.models import Token

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import UserProfile
from .secrets import redirect_uri, api, logger  # client credentials & logger

# ----------------------------- Initialize API and Logger ----------------------------- #

# Initialize client credentials from Django settings
client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI

# Initialize the Ossapi instance with client credentials
api = Ossapi(client_id, client_secret)

# ---------------------------------------------------------------------------
# Authentication views
# ---------------------------------------------------------------------------

def osu_callback(request):
    """Callback function to handle OAuth response and exchange code for an access token."""
    code = request.GET.get('code')

    if code:
        # Construct the token exchange URL dynamically
        token_url = 'https://osu.ppy.sh/oauth/token'
        payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,  # Dynamically pulled from settings
        }
        response = requests.post(token_url, data=payload)

        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access_token')

            # Save user data and login
            if access_token:
                try:
                    save_user_data(access_token, request)
                except PermissionError:
                    # Banned or not allowed; message already set inside helper
                    return redirect('error_page')
                except Exception:
                    logger.exception("Failed to save user data during osu OAuth callback")
                    messages.error(request, "Login failed while fetching your osu! profile. Please try again.")
                    return redirect('error_page')
                return redirect('home')  # Redirect to your app page after login
            else:
                messages.error(request, "Failed to retrieve access token.")
                return redirect('error_page')
        else:
            messages.error(request, f"Error during token exchange: {response.status_code}")
            return redirect('error_page')
    else:
        messages.error(request, "Authorization code not found in request.")
        return redirect('error_page')


def get_user_data_from_api(access_token):
    """Fetch user data from the osu! API using the access token."""
    # /me includes identity plus default-mode statistics (global_rank).
    url = "https://osu.ppy.sh/api/v2/me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def _positive_int_or_none(value):
    if value is None or value is False:
        return None
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _get_value(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_global_rank(user_data):
    """Return osu! global rank from an osu user payload or ossapi User, or None if unranked."""
    if user_data is None:
        return None

    stats = _get_value(user_data, 'statistics')
    rank = _positive_int_or_none(_get_value(stats, 'global_rank'))
    if rank is not None:
        return rank

    rank = _positive_int_or_none(_get_value(_get_value(stats, 'rank'), 'global'))
    if rank is not None:
        return rank

    osu_stats = _get_value(_get_value(user_data, 'statistics_rulesets'), 'osu')
    return _positive_int_or_none(_get_value(osu_stats, 'global_rank'))


def profile_updates_from_osu_data(user_data):
    return {
        'profile_pic_url': user_data.get('avatar_url', '') or '',
        'rank_at_last_login': extract_global_rank(user_data),
    }


USER_RANK_REFRESH_LOCK_KEY = 'echo_userprofile_rank_refresh'


def _wait_while_users_interacting():
    while True:
        try:
            cnt = int(cache.get('user_interaction_counter') or 0)
        except Exception:
            cnt = 0
        wait = cnt > 0
        if not wait:
            try:
                pause_until = float(cache.get('user_interaction_pause_until') or 0)
                wait = pause_until > timezone.now().timestamp()
            except Exception:
                wait = False
        if not wait:
            break
        time.sleep(1)


def refresh_all_user_ranks(*, delay_s=1.0, wait_for_idle=True, api_client=None):
    """Fetch current osu! ranks for every UserProfile and store them.

    Returns a dict with updated/unchanged/failed counts.
    """
    from ossapi.enums import UserLookupKey

    client = api_client if api_client is not None else api
    updated = 0
    unchanged = 0
    failed = 0

    queryset = UserProfile.objects.exclude(osu_id__isnull=True).exclude(osu_id='')
    for profile in queryset.iterator(chunk_size=200):
        if wait_for_idle:
            _wait_while_users_interacting()
        try:
            osu_id = int(str(profile.osu_id).strip())
        except (TypeError, ValueError):
            failed += 1
            continue
        try:
            user = client.user(osu_id, key=UserLookupKey.ID)
            rank = extract_global_rank(user)
        except Exception as exc:
            logger.warning('Failed to refresh rank for osu_id=%s: %s', profile.osu_id, exc)
            failed += 1
            if delay_s:
                time.sleep(delay_s)
            continue
        if profile.rank_at_last_login != rank:
            profile.rank_at_last_login = rank
            profile.save(update_fields=['rank_at_last_login'])
            updated += 1
        else:
            unchanged += 1
        if delay_s:
            time.sleep(delay_s)

    return {'updated': updated, 'unchanged': unchanged, 'failed': failed}


def save_user_data(access_token, request):
    """Save user data retrieved from the osu! API and authenticate the user.

    If the user is banned, redirect to the error page with the ban reason.
    """
    user_data = get_user_data_from_api(access_token)

    osu_id = str(user_data['id'])
    username = user_data['username']

    # Ensure we identify returning users by osu_id, and update username if it changed
    with transaction.atomic():
        # Try to find an existing profile by osu_id first
        user_profile = UserProfile.objects.select_related('user').filter(osu_id=osu_id).first()

        if user_profile:
            user = user_profile.user
            # If username changed on osu!, update the local Django user
            if user.username != username:
                conflict_user = User.objects.filter(username=username).exclude(pk=user.pk).first()
                if conflict_user:
                    # Preserve any data; rename the conflicting user deterministically
                    conflict_user.username = f"{conflict_user.username}__old__{conflict_user.id}"
                    conflict_user.save(update_fields=['username'])
                user.username = username
                user.save(update_fields=['username'])

            osu_updates = profile_updates_from_osu_data(user_data)
            for field, value in osu_updates.items():
                setattr(user_profile, field, value)
            user_profile.save(update_fields=list(osu_updates))

        else:
            # First login for this osu_id (or previous data was inconsistent). Prefer reusing an existing user with the same username.
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create(username=username)

            # Attach or create profile with the osu_id
            existing_profile = UserProfile.objects.filter(user=user).first()
            osu_updates = profile_updates_from_osu_data(user_data)
            if existing_profile:
                extra_fields = []
                if existing_profile.osu_id != osu_id:
                    existing_profile.osu_id = osu_id
                    extra_fields.append('osu_id')
                for field, value in osu_updates.items():
                    setattr(existing_profile, field, value)
                existing_profile.save(update_fields=extra_fields + list(osu_updates))
                user_profile = existing_profile
            else:
                user_profile = UserProfile.objects.create(
                    user=user,
                    osu_id=osu_id,
                    **osu_updates,
                )

    # Check if the user is banned
    if user_profile.banned:
        # Add an error message with the ban reason
        messages.error(request, f"You have been banned: {user_profile.ban_reason}")
        # Signal to the caller to handle the redirect
        raise PermissionError("Banned user attempted to log in")

    try:
        from django.conf import settings as dj_settings
        admin_ids = set([x.strip() for x in (dj_settings.ADMIN_OSU_IDS or '').split(',') if x.strip()])
        if osu_id in admin_ids:
            fields_to_update = []
            if not user.is_staff:
                user.is_staff = True
                fields_to_update.append('is_staff')
            if not user.is_superuser:
                user.is_superuser = True
                fields_to_update.append('is_superuser')
            if fields_to_update:
                user.save(update_fields=fields_to_update)
    except Exception:
        pass

    # Authenticate and log in the user
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)

    # Store osu_id in session for future use
    request.session['osu_id'] = osu_id

    # Generate or retrieve the token for the user
    token, _ = Token.objects.get_or_create(user=user)


# Removed: obsolete api_token view (no template; tokens handled in settings page)
