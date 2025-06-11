# echosu/views/secrets.py
"""Shared secrets and API client initialization.
This module initializes the Ossapi client with credentials and sets up a logger for the application.
It is used across various views to interact with the osu! API.
"""

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import logging

# ---------------------------------------------------------------------------
# Third-party imports
# ---------------------------------------------------------------------------
from ossapi import Ossapi

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.conf import settings


# ----------------------------- Initialize API and Logger ----------------------------- #

client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI

# Initialize the Ossapi instance with client credentials
api = Ossapi(client_id, client_secret)

# Set up a logger for this module
logger = logging.getLogger(__name__)