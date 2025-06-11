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

    # Find or create a Django user
    user, created = User.objects.get_or_create(username=username)

    # Update or create the user profile
    user_profile, profile_created = UserProfile.objects.get_or_create(user=user)
    user_profile.osu_id = osu_id
    user_profile.profile_pic_url = user_data.get('avatar_url', '')  # Use get to avoid KeyError
    user_profile.save()

    # Check if the user is banned
    if user_profile.banned:
        # Add an error message with the ban reason
        messages.error(request, f"You have been banned: {user_profile.ban_reason}")
        # Redirect to the error page
        return redirect('error_page')

    # Grant superuser and staff status if the osu! ID matches a specific ID
    if osu_id in ("4978940", "9396661"):
        user.is_superuser = True
        user.is_staff = True
        user.save()

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
