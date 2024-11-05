# ----------------------------- Imports ----------------------------- #

# Standard library imports
import json  # Used in profile view
import logging  # Used in API views
import re  # Used in search_results view
from collections import Counter  # Used in profile view

# Third-party imports
import requests  # Used in osu_callback, get_user_data_from_api
from ossapi import Ossapi  # Used in beatmap_info

# Django imports
from django.conf import settings  # Used in initialization and settings
from django.contrib import messages  # Used in beatmap_info, osu_callback
from django.contrib.auth import login  # Used in save_user_data
from django.contrib.auth.decorators import login_required  # Used in modify_tag, settings
from django.contrib.auth.models import User  # Used in save_user_data, modify_tag
from django.db.models import Count, F, FloatField, Q  # Used in multiple views
from django.db.models.functions import Coalesce  # Used in search_results
from django.http import JsonResponse  # Used in get_tags, modify_tag, search_tags
from django.shortcuts import get_object_or_404, redirect, render  # Used in multiple views

# REST framework imports
from rest_framework import viewsets  # Used in API viewsets
from rest_framework.decorators import action, api_view, permission_classes  # Used in API views
from rest_framework.response import Response  # Used in API views

# Local application imports
from .models import Beatmap, Tag, TagApplication, UserProfile   # Used in multiple views
from .serializers import (
    BeatmapSerializer, TagSerializer,
    TagApplicationSerializer, UserProfileSerializer
)  # Used in API viewsets

# ------------------------------------------------------------------------------------- #

# ----------------------------- Initialize API and Logger ----------------------------- #

# Initialize client credentials from Django settings
client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI

# Initialize the Ossapi instance with client credentials
api = Ossapi(client_id, client_secret)

# Set up a logger for this module
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------------- #

# ----------------------------- Constants ----------------------------- #

GAME_MODE_MAPPING = {
    'GameMode.OSU': 'osu',
    'GameMode.TAIKO': 'taiko',
    'GameMode.CATCH': 'fruits',
    'GameMode.MANIA': 'mania',
}

# ----------------------------- Authentication Views ----------------------------- #

def osu_callback(request):
    """
    Callback function to handle OAuth response and exchange code for access token.
    """
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
                return redirect('home')  # Redirect to your app page after logina
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
    """
    Fetch user data from osu API using the access token.
    """
    url = "https://osu.ppy.sh/api/v2/me"  # URL to osu API for user data
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


from rest_framework.authtoken.models import Token

def save_user_data(access_token, request):
    """
    Save user data retrieved from osu API and authenticate the user.
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
        # Redirect to the error_page
        return redirect('error_page')

    # Grant superuser and staff status if the Osu ID matches a specific ID
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


from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from rest_framework.authtoken.models import Token

@login_required
def api_token(request):
    user = request.user
    token, _ = Token.objects.get_or_create(user=user)
    context = {
        'token': token.key,
    }
    return render(request, 'api_token.html', context)



# ------------------------------------------------------------------------------- #

# ----------------------------- Home, tag_library, and Admin Views ----------------------------- #

def home(request):
    """Render the home page."""
    return render(request, 'home.html')

def about(request):
    """Render the about page."""
    return render(request, 'about.html')

def admin(request):
    """Redirect to the admin panel."""
    return redirect('/admin/')

def error_page_view(request):
    """
    Render the error_page template.
    """
    return render(request, 'error_page.html')

def tag_library(request):
    # Retrieve all tags ordered alphabetically and annotate with beatmap count
    tags = Tag.objects.annotate(beatmap_count=Count('beatmaps')).order_by('name')
    
    context = {
        'tags': tags
    }
    return render(request, 'tag_library.html', context)

# ------------------------------------------------------------------------ #

# ----------------------------- Beatmap Detail Views ----------------------------- #

def beatmap_detail(request, beatmap_id):
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Get TagApplications for this beatmap
    tag_apps = TagApplication.objects.filter(beatmap=beatmap).select_related('tag')

    # Annotate tags with apply counts
    tags_with_counts = tag_apps.values('tag__id', 'tag__name', 'tag__description', 'tag__description_author').annotate(
        apply_count=Count('id')
    ).order_by('-apply_count')

    # Determine if the user has applied each tag
    user_applied_tags = []
    if request.user.is_authenticated:
        user_applied_tags = TagApplication.objects.filter(
            beatmap=beatmap, user=request.user
        ).values_list('tag__id', flat=True)

    # Prepare tags_with_counts with is_applied_by_user flag
    tags_with_counts = [
        {
            'tag__id': tag['tag__id'],
            'tag__name': tag['tag__name'],
            'tag__description': tag['tag__description'],
            'tag__description_author': tag['tag__description_author'],
            'apply_count': tag['apply_count'],
            'is_applied_by_user': tag['tag__id'] in user_applied_tags
        }
        for tag in tags_with_counts
    ]

    # Prepare tags_query_string for "Find Similar Maps" link
    top_N = 10
    top_tags = [tag['tag__name'] for tag in tags_with_counts[:top_N] if tag['tag__name']]
    encapsulated_tags = [f'"{tag}"' if ' ' in tag else tag for tag in top_tags]
    tags_query_string = ' '.join(encapsulated_tags)

    # Calculate star_min and star_max based on current beatmap's star rating for "Find Similar Maps" link
    current_star = beatmap.difficulty_rating
    star_min = max(0, current_star - 0.6)
    star_max = min(15, current_star + 0.6)

    # Calculate bpm_min and bpm_max based on current beatmap's bpm for "Find Similar Maps" link
    current_bpm = beatmap.bpm
    bpm_min = (current_bpm - 10)
    bpm_max = (current_bpm + 10)

    context = {
        'beatmap': beatmap,
        'tags_with_counts': tags_with_counts,
        'tags_query_string': tags_query_string,
        'star_min': star_min,
        'star_max': star_max,
        'bpm_min': bpm_min,
        'bpm_max': bpm_max,
    }

    return render(request, 'beatmap_detail.html', context)


from django.views.decorators.http import require_POST
from .fetch_genre import fetch_genres, get_or_create_genres

@require_POST
def update_beatmap_info(request):
    beatmap_id = request.POST.get('beatmap_id')
    status_mapping = {
        -2: "Graveyard",
        -1: "WIP",
        0: "Pending",
        1: "Ranked",
        2: "Approved",
        3: "Qualified",
        4: "Loved"
    }
    
    try:
        # Fetch beatmap data from the osu! API
        beatmap_data = api.beatmap(beatmap_id)
        if not beatmap_data:
            logger.warning(f"Beatmap ID {beatmap_id} not found in osu! API.")
            return JsonResponse({'error': 'Beatmap not found in osu! API.'}, status=404)

        # Get or create the beatmap object
        beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)
        if created:
            logger.info(f"Created new Beatmap with ID: {beatmap_id}")
        else:
            logger.info(f"Updating existing Beatmap with ID: {beatmap_id}")

        # Update fields with latest data
        beatmap.title = beatmap_data._beatmapset.title
        beatmap.artist = beatmap_data._beatmapset.artist
        beatmap.creator = beatmap_data._beatmapset.creator
        beatmap.cover_image_url = getattr(beatmap_data._beatmapset.covers, 'cover_2x', None)  # Use getattr to avoid errors
        beatmap.total_length = beatmap_data.total_length
        beatmap.bpm = beatmap_data.bpm
        beatmap.cs = beatmap_data.cs
        beatmap.drain = beatmap_data.drain
        beatmap.accuracy = beatmap_data.accuracy
        beatmap.ar = beatmap_data.ar
        beatmap.difficulty_rating = beatmap_data.difficulty_rating
        beatmap.status = status_mapping.get(beatmap_data.status.value, "Unknown")
        beatmap.playcount = beatmap_data.playcount
        beatmap.favourite_count = getattr(beatmap_data._beatmapset, 'favourite_count', 0)

        # Map the game mode to the desired string representation
        api_mode_value = getattr(beatmap_data, 'mode', beatmap.mode)
        beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode_value), 'unknown')

        # Save the updated beatmap to the database
        beatmap.save()
        logger.info(f"Saved Beatmap with ID: {beatmap_id}")

        # Fetch and associate genres
        genres = fetch_genres(beatmap.artist, beatmap.title)
        logger.debug(f"Fetched genres for Beatmap '{beatmap_id}': {genres}")

        if genres:
            genre_objects = get_or_create_genres(genres)
            beatmap.genres.set(genre_objects)  # Replace existing genres with new ones
            logger.info(f"Associated genres {genres} with Beatmap '{beatmap_id}'.")
        else:
            logger.info(f"No genres found for Beatmap '{beatmap_id}'. Clearing existing genres.")
            beatmap.genres.clear()  # Optionally clear existing genres if none are fetched

        return JsonResponse({'message': 'Beatmap info updated successfully.'})

    except Exception as e:
        logger.error(f"Error updating Beatmap '{beatmap_id}': {e}")
        return JsonResponse({'error': str(e)}, status=500)



# --------------------------------------------------------------------- #

# ----------------------------- Tag Views ----------------------------- #


def get_tags(request):
    """
    Retrieve tags for a specific beatmap
    """
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Fetch all tags for this beatmap with a count of distinct users that applied each tag
    tags_with_user_counts = TagApplication.objects.filter(
        beatmap=beatmap
    ).values('tag__name', 'tag__description', 'tag__description_author__username').annotate(
        apply_count=Count('user', distinct=True)
    ).order_by('-apply_count')

    if request.user.is_authenticated:
        # Fetch all TagApplication instances for the current user and this beatmap
        user_tag_names = set(TagApplication.objects.filter(
            user=user, beatmap=beatmap
        ).values_list('tag__name', flat=True))
    else:
        user_tag_names = []

    # Construct the list of dictionaries
    tags_with_counts_list = [
        {
            'name': tag['tag__name'],
            'description': tag.get('tag__description', 'No description abaliable.'),
            'description_author': tag.get('tag__description_author__username', ''),
            'apply_count': tag['apply_count'],
            'is_applied_by_user': tag['tag__name'] in user_tag_names
        } for tag in tags_with_user_counts
    ]

    return JsonResponse(tags_with_counts_list, safe=False)


def search_tags(request):
    """
    Search for tags based on a query.
    """
    search_query = request.GET.get('q', '')
    tags = Tag.objects.filter(name__icontains=search_query).annotate(
        beatmap_count=Count('beatmaps')
    ).values('name', 'beatmap_count').order_by('-beatmap_count')
    return JsonResponse(list(tags), safe=False)


from better_profanity import profanity
import unicodedata

def sanitize_tag(tag):
    """
    Sanitize the tag by performing the following steps:
    1. Trim leading and trailing spaces.
    2. Collapse multiple consecutive spaces into one.
    3. Reduce any character repeated more than twice consecutively to two.
    4. Normalize Unicode characters to NFC form.
    5. Remove non-printable and control characters.
    6. Prevent leading or trailing non-alphanumeric characters.
    """
    # Step 1: Trim leading and trailing spaces
    tag = tag.strip()
    
    # Step 2: Collapse multiple consecutive spaces into one
    tag = ' '.join(tag.split())
    
    # Step 3: Reduce consecutive identical characters to two
    tag = re.sub(r'(.)\1{2,}', r'\1\1', tag)
    
    # Step 4: Unicode normalization to NFC form
    tag = unicodedata.normalize('NFC', tag)
    
    # Step 5: Remove non-printable and control characters
    # This regex matches any character that is not a printable character or space
    tag = re.sub(r'[^\x20-\x7E]', '', tag)
    
    # Step 6: Prevent leading or trailing non-alphanumeric characters
    # Remove leading non-alphanumeric characters
    tag = re.sub(r'^[^A-Za-z0-9]+', '', tag)
    # Remove trailing non-alphanumeric characters
    tag = re.sub(r'[^A-Za-z0-9]+$', '', tag)

    # limit to a maximum of 3 words
    max_words = 3
    words = tag.split()
    if len(words) > max_words:
        tag = ' '.join(words[:max_words])
    
    # Define a set of reserved words. might use this later
    """
    reserved_words = {'admin', 'null', 'undefined'}
    if tag.lower() in reserved_words:
        tag += '_tag'
    """
    
    return tag

# Define the allowed tag pattern if not already defined
ALLOWED_TAG_PATTERN = re.compile(r'^[A-Za-z0-9 _\-\/]{1,25}$')

@login_required
def modify_tag(request):
    """
    Apply or remove a tag for a beatmap by the current user.
    Additionally, remove the tag from the database if it's no longer used.
    """
    if request.method == 'POST':
        tag_name = request.POST.get('tag', '')
        beatmap_id = request.POST.get('beatmap_id')
        user = request.user

        processed_tag = sanitize_tag(tag_name.lower())

        # Disallow specific chars and set max length
        if not ALLOWED_TAG_PATTERN.match(processed_tag):
            error_message = 'Tag must be 1-25 characters long and can only contain letters, numbers, spaces, hyphens, and underscores.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Profanity filtering
        if profanity.contains_profanity(processed_tag):
            error_message = 'Tag contains inappropriate language.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Wrap the following operations in an atomic transaction to ensure data integrity
        try:
            with transaction.atomic():
                # Create the tag if it doesn't exist
                tag, created_tag = Tag.objects.get_or_create(name=processed_tag)
                beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

                # Check if the tag application already exists
                tag_application, created = TagApplication.objects.get_or_create(
                    tag=tag,
                    beatmap=beatmap,
                    user=user
                )

                # If not created, it means the tag application already existed, so we remove it
                if not created:
                    tag_application.delete()

                    # After deletion, check if the tag has any remaining applications
                    remaining_applications = TagApplication.objects.filter(tag=tag).exists()
                    if not remaining_applications:
                        # If no remaining applications, delete the tag
                        tag.delete()

                    return JsonResponse({'status': 'success', 'action': 'removed'})
                else:
                    # If created, a new tag application was made
                    return JsonResponse({'status': 'success', 'action': 'applied'})

        except Exception as e:
            # Log the exception as needed (optional)
            # logger.error(f"Error modifying tag: {e}")
            return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)

    # If the request method is not POST, return an error
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)


import difflib
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db import IntegrityError
from .models import Tag, Vote
from .templatetags.custom_tags import has_tag_edit_permission

def count_word_differences(old_desc, new_desc):
    old_words = old_desc.lower().split()
    new_words = new_desc.lower().split()
    diff = difflib.ndiff(old_words, new_words)
    changes = sum(1 for word in diff if word.startswith('- ') or word.startswith('+ '))
    return changes


def sanitize_description(description):
    # Step 1: Trim leading and trailing spaces
    description = description.strip()
    
    # Step 2: Collapse multiple consecutive spaces into one
    description = ' '.join(description.split())
    
    # Step 3: Reduce consecutive identical characters to two
    description = re.sub(r'(.)\1{2,}', r'\1\1', description)
    
    # Step 4: Unicode normalization to NFC form
    description = unicodedata.normalize('NFC', description)
    
    # Step 5: Remove non-printable and control characters
    description = re.sub(r'[^\x20-\x7E]', '', description)
    
    # Step 6: Remove leading and trailing non-alphanumeric characters
    description = re.sub(r'^[^A-Za-z0-9]+', '', description)
    
    return description

ALLOWED_DESCRIPTION_PATTERN = re.compile(r'^[A-Za-z0-9 .,!?\-_/\'"]{1,255}$')

@login_required
def edit_tags(request):  # Description editing
    user = request.user

    # Check if the user has permission to edit tags
    if not has_tag_edit_permission(user):
        return HttpResponseForbidden("You do not have permission to edit tags.")

    if request.method == 'POST':
        # Handle AJAX tag description updates
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            tag_id = request.POST.get('tag_id')
            new_description = request.POST.get('description', '').strip()
            
            if tag_id and new_description:
                # Sanitize the description
                processed_description = sanitize_description(new_description)
                
                # Validate Description Length
                if len(processed_description) == 0:
                    return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
                if len(processed_description) > 100:
                    return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)
                
                # Validate Allowed Characters using Regex
                if not ALLOWED_DESCRIPTION_PATTERN.match(processed_description):
                    error_message = 'Description contains invalid characters. Allowed characters are letters, numbers, spaces, and basic punctuation (. , ! ? - _ / \' ").'
                    return JsonResponse({'status': 'error', 'message': error_message}, status=400)


                # Check the entire description for profanity
                if profanity.contains_profanity(processed_description):
                    error_message = 'Description contains inappropriate language.'
                    return JsonResponse({'status': 'error', 'message': error_message}, status=400)
                
                tag = get_object_or_404(Tag, id=tag_id)
                old_description = tag.description
                word_diff_count = count_word_differences(old_description, processed_description)
                
                # Update the description
                tag.description = processed_description
                
                # Update description_author if at least 3 words have changed
                if word_diff_count >= 3:
                    tag.description_author = user  # Assign User instance
                
                tag.save()
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Tag description updated.',
                    'word_diff_count': word_diff_count,
                    'description_author': tag.description_author.username if tag.description_author else 'N/A',
                    'upvotes': tag.upvotes,
                    'downvotes': tag.downvotes,
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)
        else:
            return HttpResponseBadRequest("Invalid request method.")

    else:
        # Handle GET requests with search and pagination
        search_query = request.GET.get('search', '').strip()

        if search_query:
            tags = Tag.objects.filter(name__icontains=search_query).order_by('name')
        else:
            tags = Tag.objects.all().order_by('name')

        # Paginate tags
        paginator = Paginator(tags, 20)  # Show 10 tags per page
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'tags': page_obj,  # Pass the Page object to the template
            'search_query': search_query,
        }
        return render(request, 'edit_tags.html', context)

@login_required
def vote_description(request):
    """
    Handle AJAX requests to upvote or downvote a tag's description.
    Supports toggling and switching votes.
    """
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        tag_id = request.POST.get('tag_id')
        vote_type = request.POST.get('vote_type')

        if not tag_id or vote_type not in ['upvote', 'downvote']:
            return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

        tag = get_object_or_404(Tag, id=tag_id)
        user = request.user

        try:
            existing_vote = Vote.objects.get(user=user, tag=tag)
            if existing_vote.vote_type == vote_type:
                # User clicked the same vote button again: Remove the vote
                existing_vote.delete()
                if vote_type == Vote.UPVOTE:
                    tag.upvotes -= 1
                else:
                    tag.downvotes -= 1
                vote_removed = True
                vote_changed = False
                new_vote = False
            else:
                # User clicked the opposing vote button: Change the vote
                if existing_vote.vote_type == Vote.UPVOTE:
                    tag.upvotes -= 1
                else:
                    tag.downvotes -= 1

                existing_vote.vote_type = vote_type
                existing_vote.save()

                if vote_type == Vote.UPVOTE:
                    tag.upvotes += 1
                else:
                    tag.downvotes += 1

                vote_removed = False
                vote_changed = True
                new_vote = False
        except Vote.DoesNotExist:
            # No existing vote: Create a new vote
            Vote.objects.create(user=user, tag=tag, vote_type=vote_type)
            if vote_type == Vote.UPVOTE:
                tag.upvotes += 1
            else:
                tag.downvotes += 1
            vote_removed = False
            vote_changed = False
            new_vote = True

        # Check if the vote causes the description to be locked
        if (tag.upvotes - tag.downvotes) >= 10:
            tag.is_locked = True
        elif (tag.upvotes - tag.downvotes) < 10 and tag.is_locked:
            tag.is_locked = False  # Optionally unlock if score drops below threshold

        tag.save()

        return JsonResponse({
            'status': 'success',
            'message': 'Vote recorded.' if new_vote or vote_changed else 'Vote removed.',
            'upvotes': tag.upvotes,
            'downvotes': tag.downvotes,
            'is_locked': tag.is_locked,
            'tag_name': tag.name,
            'removed': vote_removed,
            'changed': vote_changed,
            'new_vote': new_vote,
            'current_vote': vote_type if new_vote or vote_changed else None,
        })

    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

ALLOWED_DESCRIPTION_PATTERN = re.compile(r'^[A-Za-z0-9 .,!?\-_/\'"]{1,255}$')

from better_profanity import profanity

@login_required
def update_tag_description(request):
    """
    Handle AJAX requests to update a tag's description.
    """
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        tag_id = request.POST.get('tag_id')
        new_description = request.POST.get('description', '').strip()
        user = request.user

        # Permission Check
        if not has_tag_edit_permission(user):
            return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

        # Validate Tag ID
        tag = get_object_or_404(Tag, id=tag_id)

        # Validate Description Length
        if len(new_description) == 0:
            return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
        if len(new_description) > 100:
            return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)

        # Validate Allowed Characters using Regex
        if not ALLOWED_DESCRIPTION_PATTERN.match(new_description):
            error_message = 'Description contains invalid characters. Allowed characters are letters, numbers, spaces, and basic punctuation (. , ! ? - _ / \' ").'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Check the entire description for profanity
        if profanity.contains_profanity(new_description):
            error_message = 'Tag contains inappropriate language.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Update Description
        try:
            with transaction.atomic():
                tag.description = new_description
                tag.save()
            return JsonResponse({'status': 'success', 'message': 'Description updated successfully.'})
        except Exception as e:
            # Log the exception as needed (optional)
            return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)



# ------------------------------------------------------------------------------ #

# ----------------------------- Profile Views ----------------------------- #

def profile(request):
    """
    User profile view displaying tagging statistics.
    """
    if request.user.is_authenticated:
        user_tags = TagApplication.objects.filter(user=request.user).select_related('beatmap')

        # Calculate accuracy of user's tagging
        total_tags = user_tags.count()
        agreed_tags = sum(1 for tag_app in user_tags if tag_app.agreed_by_others())
        accuracy = (agreed_tags / total_tags * 100) if total_tags > 0 else 0

        # Prepare data for the pie chart
        tag_counts = Counter(tag_app.tag.name for tag_app in user_tags)
        most_common_tags = tag_counts.most_common(10)
        tag_labels = [tag for tag, count in most_common_tags]
        tag_data = [count for tag, count in most_common_tags]

        context = {
            'user_tags': user_tags,
            'accuracy': accuracy,
            'tag_labels': json.dumps(tag_labels),
            'tag_data': json.dumps(tag_data),
        }

        return render(request, 'profile.html', context)
    else:
        return redirect('login')  # Redirect to login if user is not authenticated

# ------------------------------------------------------------------------ #

# ----------------------------- Search Views ----------------------------- #

from django.shortcuts import render
from django.db.models import Q, Count, Value, IntegerField
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from .models import Beatmap, TagApplication, Tag
import re
from collections import defaultdict


def search_results(request):

    ############################################
    from nltk.stem import PorterStemmer
    from django.db.models import Count, Q, F
    import shlex

    # Initialize the stemmer
    stemmer = PorterStemmer()

    def stem_word(word):
        """Stems a single word."""
        return stemmer.stem(word.lower())

    def stem_phrase(phrase):
        """Stems each word in a multi-word phrase."""
        return ' '.join(stem_word(word) for word in phrase.split())

    def parse_query_with_quotes(raw_query):
        """
        Parses the raw search query and returns a list of tuples: Each tuple contains (term, is_quoted)
        Handles unmatched quotes by ignoring them.
        """
        lexer = shlex.shlex(raw_query, posix=True)
        lexer.whitespace_split = True
        lexer.quotes = '"\''
        tokens = []
        
        try:
            for token in lexer:
                is_quoted = ' ' in token
                tokens.append((token, is_quoted))
        except ValueError as e:
            # Handle the unmatched quotes by stripping them and re-parsing
            print(f"Warning: {e}. Attempting to parse without unmatched quotes.")
            # Remove all quotes and split the string
            fixed_query = raw_query.replace('"', '').replace("'", "")
            lexer = shlex.shlex(fixed_query, posix=True)
            lexer.whitespace_split = True
            lexer.quotes = ''  # Disable quoting
            for token in lexer:
                tokens.append((token, False))
        
        return tokens

    def process_search_terms(parsed_terms):
        """
        Processes parsed search terms by sanitizing and stemming.

        Args:
            parsed_terms (list of tuples): List of (term, is_quoted).

        Returns:
            set: Set of stemmed sanitized search terms.
        """
        stemmed_search_terms = set()
        for term, is_quoted in parsed_terms:
            # Sanitize the term by stripping quotes
            sanitized_term = term.strip('"\'')
            if ' ' in sanitized_term:
                # If multi-word, stem each word
                stemmed_term = stem_phrase(sanitized_term)
            else:
                # If single-word, stem directly
                stemmed_term = stem_word(sanitized_term)
            stemmed_search_terms.add(stemmed_term)
        return stemmed_search_terms

    def identify_exact_match_tags(include_tag_names, stemmed_search_terms):
        """
        Identifies exact match tag names based on stemmed search terms.

        Args:
            include_tag_names (set): Set of tag names to include.
            stemmed_search_terms (set): Set of stemmed search terms.

        Returns:
            set: Set of exact match tag names.
        """
        exact_match_tag_names = set()
        for tag in include_tag_names:
            sanitized_tag = tag.strip('"\'')
            if ' ' in sanitized_tag:
                # Stem each word in the tag
                stemmed_tag = stem_phrase(sanitized_tag)
            else:
                stemmed_tag = stem_word(sanitized_tag)
            if stemmed_tag in stemmed_search_terms:
                exact_match_tag_names.add(tag)
            else:
                # Additionally, check if any word in the tag matches
                for word in sanitized_tag.split():
                    if stem_word(word) in stemmed_search_terms:
                        exact_match_tag_names.add(tag)
                        break
        return exact_match_tag_names

    def annotate_and_order_beatmaps(beatmaps, include_tag_names, exact_match_tag_names, sort_method):
        """
        Annotates the beatmaps queryset with tag counts and weights, then orders them.

        Args:
            beatmaps (QuerySet): The beatmaps queryset.
            include_tag_names (set): Set of tag names to include.
            exact_match_tag_names (set): Set of exact match tag names.
            sort_method (str): The sorting method ('tag_weight' or 'popularity').

        Returns:
            QuerySet: Annotated and ordered queryset.
        """
        if sort_method == 'tag_weight':
            annotated_beatmaps = beatmaps.annotate(
                tag_match_count=Count(
                    'tags',
                    filter=Q(tags__name__in=include_tag_names),
                ),
                tag_apply_count=Count(
                    'tagapplication',
                    filter=Q(tags__name__in=include_tag_names)
                ),
                exact_match_total_count=Count(
                    'tags',
                    filter=Q(tags__name__in=exact_match_tag_names),
                ),
                exact_match_distinct_count=Count(
                    'tags',
                    filter=Q(tags__name__in=exact_match_tag_names),
                    distinct=True
                )
            ).annotate(
                # Define weight with higher priority for exact matches
                tag_weight=(
                    F('exact_match_distinct_count') * 3.0 + F('exact_match_total_count') * 0.3 + F('tag_match_count') * 0.5 + F('tag_apply_count') * 0.01
                ),
                popularity=F('favourite_count') * 0.5 + F('playcount') * 0.001,
            ).order_by('-tag_weight')  # Order by weight descending

        elif sort_method == 'popularity':
            annotated_beatmaps = beatmaps.annotate(
                tag_match_count=Count(
                    'tags',
                    filter=Q(tags__name__in=include_tag_names),
                ),
                tag_apply_count=Count(
                    'tagapplication',
                    filter=Q(tags__name__in=include_tag_names)
                ),
                exact_match_count=Count(
                    'tags',
                    filter=Q(tags__name__in=exact_match_tag_names),
                ),
                exact_match_distinct_count=Count(
                    'tags',
                    filter=Q(tags__name__in=exact_match_tag_names),
                    distinct=True
                )
            ).annotate(
                # Define weight with higher priority for exact matches
                tag_weight=(
                    F('exact_match_distinct_count') * 3.0 + F('exact_match_total_count') * 0.3 + F('tag_match_count') * 0.5 + F('tag_apply_count') * 0.01
                ),
                popularity=F('favourite_count') * 0.5 + F('playcount') * 0.001,
            ).order_by('-popularity')  # Order by popularity descending

        else:
            # Default sorting
            annotated_beatmaps = beatmaps.order_by('-favourite_count', '-playcount')

        return annotated_beatmaps
    ############################################


    # Start of the function
    query = request.GET.get('query', '').strip()
    print("Raw query string:", query)  # Debug

    selected_mode = request.GET.get('mode', 'osu').strip().lower()
    star_min = request.GET.get('star_min', '0').strip()
    star_max = request.GET.get('star_max', '15').strip()
    sort = request.GET.get('sort', '')

    # Get status filter values
    status_ranked = request.GET.get('status_ranked', False)
    status_loved = request.GET.get('status_loved', False)
    status_unranked = request.GET.get('status_unranked', False)

    # Validate and convert star ratings
    try:
        star_min = float(star_min)
        if star_min < 0:
            star_min = 0.0
    except ValueError:
        star_min = 0.0
    try:
        star_max = float(star_max)
        if star_max < star_min:
            star_max = 15.0
    except ValueError:
        star_max = 15.0

    MODE_MAPPING = {
        'osu': 'osu',
        'taiko': 'taiko',
        'catch': 'fruits',
        'mania': 'mania',
    }

    if selected_mode not in MODE_MAPPING:
        selected_mode = 'osu'  # Default to 'osu' mode if invalid

    beatmaps = Beatmap.objects.all()

    # Filter by mode
    mapped_mode = MODE_MAPPING[selected_mode]
    if mapped_mode:
        beatmaps = beatmaps.filter(mode__iexact=mapped_mode)
    else:
        beatmaps = beatmaps.filter(mode__iexact='osu')

    # Filter by star rating
    if star_max >= 15:
        beatmaps = beatmaps.filter(difficulty_rating__gte=star_min)
    else:
        beatmaps = beatmaps.filter(difficulty_rating__gte=star_min, difficulty_rating__lte=star_max)

    # Filter by status
    if status_ranked or status_loved or status_unranked:
        status_filters = Q()
        if status_ranked:
            status_filters |= Q(status='Ranked') | Q(status='Approved')
        if status_loved:
            status_filters |= Q(status='Loved')
        if status_unranked:
            status_filters |= (
                Q(status='Graveyard') | Q(status='WIP') | Q(status='Pending') | Q(status='Qualified')
            )
        beatmaps = beatmaps.filter(status_filters)

    # Process query
    # Replace the existing parse_search_terms with enhanced parsing
    parsed_terms = parse_query_with_quotes(query)
    print("Parsed search terms:", parsed_terms)  # Debug

    # Extract just the terms without the quoted status
    search_terms = [term for term, is_quoted in parsed_terms]
    print("Search terms:", search_terms)  # Debug

    # Build query conditions
    beatmaps, include_tag_names = build_query_conditions(beatmaps, search_terms)

    # Sanitize and stem the search terms
    stemmed_search_terms = process_search_terms(parsed_terms)

    # Identify exact match tag names based on stemming
    exact_match_tag_names = identify_exact_match_tags(include_tag_names, stemmed_search_terms)

    # Determine sort method
    if sort not in ['tag_weight', 'popularity']:
        if query:
            sort = 'tag_weight'
        else:
            sort = 'popularity'

    # Annotate beatmaps with tag_match_count, tag_apply_count, and weight
    if include_tag_names:
        print("include_tag_names:", include_tag_names)
        print("exact_match_tag_names:", exact_match_tag_names)

        # Annotate and order the queryset
        beatmaps = annotate_and_order_beatmaps(beatmaps, include_tag_names, exact_match_tag_names, sort)
    else:
        beatmaps = beatmaps.annotate(
            total_tag_apply_count=Count('tagapplication'),
            tag_weight=F('total_tag_apply_count'),  # Define weight
            popularity=F('favourite_count') * 0.5 + F('playcount') * 0.001,
        )
        # Apply sorting based on user preference
        if sort == 'tag_weight':
            beatmaps = beatmaps.order_by('-tag_weight')
        elif sort == 'popularity':
            beatmaps = beatmaps.order_by('-popularity')
        else:
            # Default sorting if sort parameter is invalid
            beatmaps = beatmaps.order_by('-favourite_count', '-playcount')

    # Pagination
    paginator = Paginator(beatmaps, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Annotate beatmaps with tag details
    annotate_search_results_with_tags(page_obj.object_list, request.user)

    context = {
        'beatmaps': page_obj,
        'query': query,
        'star_min': star_min,
        'star_max': star_max,
        'sort': sort,
        # Pass back the status filters to the template to remember the selection
        'status_ranked': status_ranked,
        'status_loved': status_loved,
        'status_unranked': status_unranked,
    }

    return render(request, 'search_results.html', context)

#######################################################################################

from collections import defaultdict

def annotate_search_results_with_tags(beatmaps, user):
    beatmap_ids = beatmaps.values_list('id', flat=True)
    # Fetch all TagApplications related to the beatmaps
    tag_apps = TagApplication.objects.filter(beatmap_id__in=beatmap_ids).select_related('tag')
    # Mapping from beatmap_id to a dictionary of tags and counts
    beatmap_tag_counts = defaultdict(lambda: defaultdict(int))
    user_applied_tags = defaultdict(set)

    for tag_app in tag_apps:
        beatmap_id = tag_app.beatmap_id
        tag = tag_app.tag
        beatmap_tag_counts[beatmap_id][tag] += 1
        if user.is_authenticated and tag_app.user_id == user.id:
            user_applied_tags[beatmap_id].add(tag)

    # Attach the tags and counts to the beatmaps
    for beatmap in beatmaps:
        tags_with_counts = []
        beatmap_tags = beatmap_tag_counts.get(beatmap.id, {})
        for tag, count in beatmap_tags.items():
            is_applied_by_user = tag in user_applied_tags.get(beatmap.id, set())
            tags_with_counts.append({
                'tag': tag,
                'apply_count': count,
                'is_applied_by_user': is_applied_by_user,
            })
        beatmap.tags_with_counts = sorted(tags_with_counts, key=lambda x: -x['apply_count'])

    return beatmaps

#######################################################################################

def parse_search_terms(query):
    """
    Use regular expression to split the query into terms, treating quoted strings as single terms.
    """
    return re.findall(r'[-.]?"[^"]+"|[-.]?[^"\s]+', query)

#######################################################################################

from .operators import (
    handle_quotes,
    handle_exclusion,
    handle_inclusion,
    handle_attribute_queries,
    handle_general_inclusion
)
from .utils import QueryContext

def build_query_conditions(beatmaps, search_terms):
    """
    Build inclusion, exclusion, and required tag conditions based on the search terms.
    """
    context = QueryContext(beatmaps)
    
    # Define the order of operations
    query_operations = [
        handle_attribute_queries,
        handle_quotes,
        handle_exclusion,
        handle_inclusion,
        handle_general_inclusion
    ]
    
    # Apply each operator function in order
    for operation in query_operations:
        search_terms = operation(context, search_terms)
        if context.beatmaps is None or not context.beatmaps.exists():
            break  # Early exit if no beatmaps match
    
    # Apply inclusion Q objects
    if context.include_q:
        context.beatmaps = context.beatmaps.filter(context.include_q)
    
    # Apply exclusion Q objects
    if context.exclude_q:
        context.beatmaps = context.beatmaps.exclude(context.exclude_q)
    
    # Apply required tags filter
    if context.required_tags:
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.required_tags)
    
    # Apply inclusion tags filter
    if context.include_tag_names:
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.include_tag_names).distinct()
    
    # Apply exclusion tags filter
    if context.exclude_tags:
        context.beatmaps = context.beatmaps.exclude(tags__name__in=context.exclude_tags)
    
    return context.beatmaps, context.include_tag_names


# ------------------------------------------------------------------------ #

# ----------------------------- Settings View ----------------------------- #

@login_required
def settings(request):
    if request.method == 'POST' and 'generate_token' in request.POST:
        CustomToken.objects.filter(user=request.user).delete()
        token, raw_key = CustomToken.create_token(request.user)
        print(f"raw_key passed to template from view: {raw_key}")
        return render(request, 'settings.html', {'full_key': raw_key, 'user': request.user})
    else:
        return render(request, 'settings.html', {'user': request.user})




from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction


@login_required
def confirm_data_deletion(request):
    return render(request, 'confirm_data_deletion.html')

@login_required
def delete_user_data(request):
    if request.method == 'POST':
        user = request.user
        try:
            with transaction.atomic():
                # Delete user's tag applications
                TagApplication.objects.filter(user=user).delete()

                # Delete other related data if necessary
                # For example, user profile
                if hasattr(user, 'profile'):
                    user.profile.delete()

                # Do NOT delete the user account

            messages.success(request, 'Your contributions have been successfully deleted.')
            return redirect('settings')

        except Exception as e:
            messages.error(request, 'An error occurred while deleting your data.')
            print(e)
            return redirect('settings')
    else:
        return redirect('settings')




# ------------------------------------------------------------------------ #

# ----------------------------- Home View ----------------------------- #

from django.shortcuts import render
from django.db.models import Count
from django.contrib.auth.decorators import login_required

def get_top_tags(user=None):
    # Annotate tags with total usage and get top 50 tags
    tags = Tag.objects.annotate(total=Count('tagapplication')).filter(total__gt=0).order_by('-total').select_related('description_author')[:50]

    # Prepare tags for display
    if user and user.is_authenticated:
        user_tag_ids = TagApplication.objects.filter(user=user).values_list('tag_id', flat=True)
        for tag in tags:
            tag.is_applied_by_user = tag.id in user_tag_ids
    else:
        for tag in tags:
            tag.is_applied_by_user = False

    return tags




from collections import defaultdict
from django.template.loader import render_to_string

def get_recommendations(user=None, limit=5, offset=0):
    if user and user.is_authenticated:
        # Get a list of tag IDs applied by the user
        user_tags = list(TagApplication.objects.filter(user=user).values_list('tag_id', flat=True))

        if user_tags:
            # User has applied tags; generate recommendations based on these tags

            # Get beatmap IDs the user has already tagged
            user_tagged_map_ids = TagApplication.objects.filter(user=user).values_list('beatmap_id', flat=True)

            # Get beatmaps tagged with the user's tags, excluding maps the user has already tagged
            recommended_maps = Beatmap.objects.filter(
                tagapplication__tag_id__in=user_tags
            ).exclude(
                id__in=user_tagged_map_ids
            ).annotate(
                total_tags=Count('tagapplication')
            ).order_by('-total_tags').distinct()[offset:offset+limit]
        else:
            recommended_maps = Beatmap.objects.annotate(
                total_tags=Count('tagapplication')
            ).filter(
                total_tags__gt=0
            ).order_by('?')[offset:offset+limit]
    else:
        # For anonymous users, provide 5 random maps
        recommended_maps = Beatmap.objects.annotate(
            total_tags=Count('tagapplication')
        ).filter(
            total_tags__gt=0
        ).order_by('?')[offset:offset+limit]
    
    # Annotate recommended_maps with tags_with_counts
    recommended_maps = annotate_beatmaps_with_tags(recommended_maps, user)
    return recommended_maps


def annotate_beatmaps_with_tags(beatmaps, user):
    beatmap_ids = beatmaps.values_list('id', flat=True)
    # Fetch all TagApplications related to the beatmaps
    tag_apps = TagApplication.objects.filter(beatmap_id__in=beatmap_ids).select_related('tag')
    # Mapping from beatmap_id to a dictionary of tags and counts
    beatmap_tag_counts = defaultdict(lambda: defaultdict(int))
    user_applied_tags = defaultdict(set)

    for tag_app in tag_apps:
        beatmap_id = tag_app.beatmap_id
        tag = tag_app.tag
        beatmap_tag_counts[beatmap_id][tag] += 1
        if user and user.is_authenticated and tag_app.user_id == user.id:
            user_applied_tags[beatmap_id].add(tag)

    # Attach the tags and counts to the beatmaps
    for beatmap in beatmaps:
        tags_with_counts = []
        beatmap_tags = beatmap_tag_counts.get(beatmap.id, {})
        for tag, count in beatmap_tags.items():
            is_applied_by_user = tag in user_applied_tags.get(beatmap.id, set())
            tags_with_counts.append({
                'tag': tag,
                'apply_count': count,
                'is_applied_by_user': is_applied_by_user,
            })
        beatmap.tags_with_counts = sorted(tags_with_counts, key=lambda x: -x['apply_count'])

    return beatmaps


def load_more_recommendations(request):
    # Check if the request is an AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        user = request.user if request.user.is_authenticated else None
        offset = int(request.GET.get('offset', 0))
        limit = int(request.GET.get('limit', 5))

        recommended_maps = get_recommendations(user=user, limit=limit, offset=offset)

        # Render the recommended maps to an HTML string
        rendered_maps = render_to_string('partials/recommended_maps.html', {'recommended_maps': recommended_maps}, request)

        return JsonResponse({'rendered_maps': rendered_maps})
    else:
        return JsonResponse({'error': 'Invalid request'}, status=400)


def recommended_maps_view(request):
    user = request.user
    recommended_maps = get_recommendations(user=user)
    
    context = {
        'recommended_maps': recommended_maps,
    }
    
    return render(request, 'your_template.html', context)


import re
from .models import Genre
from .fetch_genre import fetch_genres, get_or_create_genres 


def home(request):
    user = request.user if request.user.is_authenticated else None

    # Fetch top tags and recommendations
    tags = get_top_tags(user)
    recommended_maps = get_recommendations(user)

    context = {
        'tags': tags,
        'recommended_maps': recommended_maps,
    }

    # Handle beatmap info form submission (POST request)
    if request.method == 'POST':
        beatmap_input = request.POST.get('beatmap_id', '').strip()

        if beatmap_input:
            try:
                # Extract the beatmap ID from the input (either full URL, partial URL, or just the ID)
                match = re.search(r'(\d+)$', beatmap_input)
                if match:
                    beatmap_id_request = match.group(1)  # Get the beatmap ID as a string
                    print(f"Processing beatmap ID: {beatmap_id_request}")

                    # Attempt to fetch beatmap data from the osu! API
                    beatmap_data = api.beatmap(beatmap_id_request)

                    if not beatmap_data:
                        raise ValueError(f"{beatmap_id_request} isn't a valid beatmap ID.")

                    # Get or create the beatmap object in the database
                    beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id_request)
                    print(f"Beatmap created: {created}")

                    # Check if beatmap data needs to be updated
                    if created or any(
                        attr is None for attr in [
                            beatmap.title, beatmap.version, beatmap.artist, beatmap.creator,
                            beatmap.cover_image_url, beatmap.total_length, beatmap.bpm,
                            beatmap.cs, beatmap.drain, beatmap.accuracy, beatmap.ar,
                            beatmap.difficulty_rating, beatmap.mode, beatmap.beatmapset_id,
                            beatmap.status, beatmap.playcount, beatmap.favourite_count
                        ]
                    ):
                        # Update beatmap attributes from the API data
                        if hasattr(beatmap_data, '_beatmapset'):
                            beatmapset = beatmap_data._beatmapset
                            beatmap.beatmapset_id = getattr(beatmapset, 'id', beatmap.beatmapset_id)
                            beatmap.title = getattr(beatmapset, 'title', beatmap.title)
                            beatmap.artist = getattr(beatmapset, 'artist', beatmap.artist)
                            beatmap.creator = getattr(beatmapset, 'creator', beatmap.creator)
                            beatmap.favourite_count = getattr(beatmapset, 'favourite_count', beatmap.favourite_count)
                            beatmap.cover_image_url = getattr(
                                getattr(beatmapset, 'covers', {}),
                                'cover_2x',
                                beatmap.cover_image_url
                            )

                        status_mapping = {
                            -2: "Graveyard",
                            -1: "WIP",
                            0: "Pending",
                            1: "Ranked",
                            2: "Approved",
                            3: "Qualified",
                            4: "Loved"
                        }

                        # Update other beatmap attributes
                        beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
                        beatmap.total_length = getattr(beatmap_data, 'total_length', beatmap.total_length)
                        beatmap.bpm = getattr(beatmap_data, 'bpm', beatmap.bpm)
                        beatmap.cs = getattr(beatmap_data, 'cs', beatmap.cs)
                        beatmap.drain = getattr(beatmap_data, 'drain', beatmap.drain)
                        beatmap.accuracy = getattr(beatmap_data, 'accuracy', beatmap.accuracy)
                        beatmap.ar = getattr(beatmap_data, 'ar', beatmap.ar)
                        beatmap.difficulty_rating = getattr(beatmap_data, 'difficulty_rating', beatmap.difficulty_rating)
                        beatmap.status = status_mapping.get(beatmap_data.status.value, "Unknown")
                        beatmap.playcount = getattr(beatmap_data, 'playcount', beatmap.playcount)
                        # Map the game mode to the desired string representation
                        api_mode_value = getattr(beatmap_data, 'mode', beatmap.mode)
                        beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode_value), 'unknown')

                        # Save the updated beatmap to the database
                        beatmap.save()
                        print("Beatmap attributes updated and saved.")

                        # Fetch and associate genres
                        # Assuming 'title' is the song name
                        genres = fetch_genres(beatmap.artist, beatmap.title)
                        print(f"Fetched genres: {genres}")
                        if genres:
                            genre_objects = get_or_create_genres(genres)
                            beatmap.genres.set(genre_objects)  # Associate genres with the beatmap
                            print(f"Associated genres {genres} with beatmap '{beatmap_id_request}'.")
                        else:
                            print(f"No genres found for beatmap '{beatmap_id_request}'.")

                    # Add the beatmap to the context to display its information
                    context['beatmap'] = beatmap
                else:
                    raise ValueError("Invalid input. Please provide a valid beatmap link or ID.")

            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
                logger.error(f"Error processing beatmap input '{beatmap_input}': {e}")
                print(f"Error: {str(e)}")

    else:
        beatmap_id = request.GET.get('beatmap_id')
        if beatmap_id:
            beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)
            context['beatmap'] = beatmap

    # If a beatmap is in context, prepare tags
    if 'beatmap' in context:
        beatmap = context['beatmap']

        # Aggregate tag applications for the beatmap
        beatmap_tags_with_counts = (
            TagApplication.objects
            .filter(beatmap=beatmap)
            .values('tag__id', 'tag__name', 'tag__description', 'tag__description_author__username')
            .annotate(apply_count=Count('id'))
        ).order_by('-apply_count')

        # Get the set of tag IDs that the current user has applied
        if request.user.is_authenticated:
            user_tag_ids = set(
                TagApplication.objects.filter(beatmap=beatmap, user=request.user).values_list('tag__id', flat=True)
            )
        else:
            user_tag_ids = set()

        # Add is_applied_by_user flag to each tag
        for tag_info in beatmap_tags_with_counts:
            tag_info['is_applied_by_user'] = tag_info['tag__id'] in user_tag_ids

        context['beatmap_tags_with_counts'] = beatmap_tags_with_counts

    return render(request, 'home.html', context)


# ------------------------------------------------------------------------ #

# ----------------------------- API Views ----------------------------- #

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count
from .models import Beatmap, Tag, TagApplication, UserProfile
from .serializers import BeatmapSerializer, TagSerializer, TagApplicationSerializer, UserProfileSerializer, TagApplicationToggleSerializer
from echo.authentication import CustomTokenAuthentication

@api_view(['GET'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def tags_for_beatmaps(request, beatmap_id=None):
    if beatmap_id:
        beatmaps = Beatmap.objects.filter(beatmap_id=beatmap_id)
        if not beatmaps.exists():
            return Response({"detail": "Beatmap not found."}, status=404)
    else:
        batch_size = int(request.GET.get('batch_size', 500))
        offset = int(request.GET.get('offset', 0))
        beatmaps = Beatmap.objects.annotate(tag_count=Count('tagapplication')).filter(
            tag_count__gt=0
        ).order_by('id')[offset:offset + batch_size]
        if not beatmaps.exists():
            return Response({"detail": "No beatmaps found."}, status=404)

    result = []
    for beatmap in beatmaps:
        tag_counts = TagApplication.objects.filter(beatmap=beatmap).values('tag__name').annotate(
            tag_count=Count('tag')
        ).order_by('-tag_count')
        tags_data = [{'tag': item['tag__name'], 'count': item['tag_count']} for item in tag_counts]
        result.append({
            'beatmap_id': beatmap.beatmap_id,
            'title': beatmap.title,
            'artist': beatmap.artist,
            'tags': tags_data
        })

    return Response(result)


from .models import CustomToken

@login_required
def generate_token(request):
    if request.method == 'POST':
        # Delete existing tokens
        CustomToken.objects.filter(user=request.user).delete()
        # Create new token
        token = CustomToken.objects.create(user=request.user)
        # Store the token key temporarily to display to the user
        token_key = token.key
        messages.success(request, 'Your API token has been generated.')
        return render(request, 'settings.html', {'token_key': token_key})
    else:
        return redirect('settings')

# ------------------------------------------------------------------------ #

# ----------------------------- API ViewSets ----------------------------- #


class BeatmapViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Beatmap.objects.all()
    serializer_class = BeatmapSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='filtered')
    def filtered(self, request):
        query = request.query_params.get('query', None)
        if query:
            # Filter beatmaps based on title, artist, or tag names
            beatmaps = Beatmap.objects.filter(
                Q(title__icontains=query) |
                Q(artist__icontains=query) |
                Q(tags__name__icontains=query)
            ).distinct()
            serializer = self.get_serializer(beatmaps, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"detail": "Query parameter 'query' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]



class TagApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TagApplication.objects.all()
    serializer_class = TagApplicationSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='toggle')
    def toggle_tags(self, request):
        """
        Toggle tags for a beatmap. Applies the tag if not already applied by the user,
        or removes it if already applied. If the beatmap does not exist in the database,
        fetch it from the osu! API and add it to the database before proceeding.
        """
        serializer = TagApplicationToggleSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            results = serializer.toggle_tags()
            return Response({
                "status": "success",
                "results": results
            }, status=status.HTTP_200_OK)
        else:
            # Check if the only error is 'beatmap_id' does not exist
            beatmap_errors = serializer.errors.get('beatmap_id', [])
            if len(serializer.errors) == 1 and "Beatmap does not exist." in beatmap_errors:
                beatmap_id = request.data.get('beatmap_id')
                if not beatmap_id:
                    # beatmap_id is missing or invalid
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    # Fetch beatmap data from osu! API
                    beatmap_data = api.beatmap(beatmap_id)
                    if not beatmap_data:
                        raise ValueError(f"{beatmap_id} isn't a valid beatmap ID.")
                    
                    # Start a transaction to ensure atomicity
                    with transaction.atomic():
                        # Get or create the beatmap object in the database
                        beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)
                        
                        # Update beatmap attributes from the API data
                        # This logic mirrors your existing 'home' view
                        if hasattr(beatmap_data, '_beatmapset'):
                            beatmapset = beatmap_data._beatmapset
                            beatmap.beatmapset_id = getattr(beatmapset, 'id', beatmap.beatmapset_id)
                            beatmap.title = getattr(beatmapset, 'title', beatmap.title)
                            beatmap.artist = getattr(beatmapset, 'artist', beatmap.artist)
                            beatmap.creator = getattr(beatmapset, 'creator', beatmap.creator)
                            beatmap.cover_image_url = getattr(
                                getattr(beatmapset, 'covers', {}),
                                'cover_2x',
                                beatmap.cover_image_url
                            )
                        
                        status_mapping = {
                            -2: "Graveyard",
                            -1: "WIP",
                            0: "Pending",
                            1: "Ranked",
                            2: "Approved",
                            3: "Qualified",
                            4: "Loved"
                        }
                        
                        # Update other beatmap attributes
                        beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
                        beatmap.total_length = getattr(beatmap_data, 'total_length', beatmap.total_length)
                        beatmap.bpm = getattr(beatmap_data, 'bpm', beatmap.bpm)
                        beatmap.cs = getattr(beatmap_data, 'cs', beatmap.cs)
                        beatmap.drain = getattr(beatmap_data, 'drain', beatmap.drain)
                        beatmap.accuracy = getattr(beatmap_data, 'accuracy', beatmap.accuracy)
                        beatmap.ar = getattr(beatmap_data, 'ar', beatmap.ar)
                        beatmap.difficulty_rating = getattr(beatmap_data, 'difficulty_rating', beatmap.difficulty_rating)
                        beatmap.mode = getattr(beatmap_data, 'mode', beatmap.mode)
                        beatmap.status = status_mapping.get(beatmap_data.status.value, "Unknown")
                        
                        # Save the updated beatmap to the database
                        beatmap.save()
                    
                    # After successfully fetching and saving the beatmap, re-validate the serializer
                    serializer = TagApplicationToggleSerializer(data=request.data, context={'request': request})
                    if serializer.is_valid():
                        results = serializer.toggle_tags()
                        return Response({
                            "status": "success",
                            "results": results
                        }, status=status.HTTP_200_OK)
                    else:
                        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
                except Exception as e:
                    # Log the error as needed
                    return Response({
                        "beatmap_id": [str(e)]
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # Return other validation errors
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

# ------------------------------------------------------------------------ #
