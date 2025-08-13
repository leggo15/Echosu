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
from django.db import transaction
from django.shortcuts import redirect, render

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
                save_user_data(access_token, request)
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
    url = "https://osu.ppy.sh/api/v2/me"  # URL to osu API for user data
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


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

            # Always refresh avatar
            user_profile.profile_pic_url = user_data.get('avatar_url', '') or ''
            user_profile.save(update_fields=['profile_pic_url'])

        else:
            # First login for this osu_id (or previous data was inconsistent). Prefer reusing an existing user with the same username.
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create(username=username)

            # Attach or create profile with the osu_id
            existing_profile = getattr(user, 'userprofile', None)
            if existing_profile:
                if existing_profile.osu_id != osu_id:
                    existing_profile.osu_id = osu_id
                    existing_profile.profile_pic_url = user_data.get('avatar_url', '') or ''
                    existing_profile.save(update_fields=['osu_id', 'profile_pic_url'])
                user_profile = existing_profile
            else:
                user_profile = UserProfile.objects.create(
                    user=user,
                    osu_id=osu_id,
                    profile_pic_url=user_data.get('avatar_url', '') or ''
                )

    # Check if the user is banned
    if user_profile.banned:
        # Add an error message with the ban reason
        messages.error(request, f"You have been banned: {user_profile.ban_reason}")
        # Redirect to the error page
        return redirect('error_page')

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


@login_required
def api_token(request):
    """Return or create a DRF token for the current user and render it."""
    user = request.user
    token, _ = Token.objects.get_or_create(user=user)
    context = {
        'token': token.key,
    }
    return render(request, 'api_token.html', context)
