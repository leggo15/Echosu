# echo/views.py

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
from rest_framework_api_key.models import APIKey  # Used in settings view
from rest_framework_api_key.permissions import HasAPIKey  # Used in API views

# Local application imports
from .models import Beatmap, Tag, TagApplication, UserProfile, CustomAPIKey  # Used in multiple views
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
                return redirect('beatmap_info')  # Redirect to your app page after login
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


def save_user_data(access_token, request):
    """
    Save user data retrieved from osu API and authenticate the user.
    """
    user_data = get_user_data_from_api(access_token)

    osu_id = str(user_data['id'])
    username = user_data['username']

    # Find or create a Django user
    user, created = User.objects.get_or_create(username=username)

    # Update or create the user profile
    user_profile, profile_created = UserProfile.objects.get_or_create(user=user)
    user_profile.osu_id = osu_id
    user_profile.profile_pic_url = user_data['avatar_url']
    user_profile.save()

    # Grant superuser and staff status if the Osu ID matches a specific ID
    if osu_id == "4978940":
        user.is_superuser = True
        user.is_staff = True
        user.save()

    # Authenticate and log in the user
    user.backend = 'django.contrib.auth.backends.ModelBackend'  # Set backend manually
    login(request, user)

    # Store osu_id in session for future use
    request.session['osu_id'] = osu_id

# ------------------------------------------------------------------------------- #

# ----------------------------- Home and Admin Views ----------------------------- #

def home(request):
    """Render the home page."""
    return render(request, 'home.html')


def admin(request):
    """Redirect to the admin panel."""
    return redirect('/admin/')

# ------------------------------------------------------------------------ #

# ----------------------------- Beatmap Views ----------------------------- #

def beatmap_info(request, beatmap_id=None):
    """
    View to display beatmap information and handle beatmap searches.
    """
    context = {}
    if beatmap_id:
        beatmap = get_object_or_404(Beatmap, pk=beatmap_id)
    else:
        beatmap = None

    if request.method == 'POST':
        beatmap_id_request = request.POST.get('beatmap_id')
        if beatmap_id_request:
            # Get or create the beatmap object
            beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id_request)

            # Check if beatmap data needs to be fetched from API
            if created or any(
                attr is None for attr in [
                    beatmap.title, beatmap.version, beatmap.artist, beatmap.creator,
                    beatmap.cover_image_url, beatmap.total_length, beatmap.bpm,
                    beatmap.cs, beatmap.drain, beatmap.accuracy, beatmap.ar,
                    beatmap.difficulty_rating, beatmap.mode
                ]
            ):
                try:
                    beatmap_data = api.beatmap(beatmap_id_request)

                    if hasattr(beatmap_data, '_beatmapset'):
                        beatmapset = beatmap_data._beatmapset
                        beatmap.title = getattr(beatmapset, 'title', None)
                        beatmap.artist = getattr(beatmapset, 'artist', None)
                        beatmap.creator = getattr(beatmapset, 'creator', None)
                        beatmap.cover_image_url = beatmapset.covers.cover_2x if hasattr(beatmapset, 'covers') else None

                    # Update beatmap attributes
                    beatmap.version = beatmap_data.version
                    beatmap.total_length = beatmap_data.total_length
                    beatmap.bpm = beatmap_data.bpm
                    beatmap.cs = beatmap_data.cs
                    beatmap.drain = beatmap_data.drain
                    beatmap.accuracy = beatmap_data.accuracy
                    beatmap.ar = beatmap_data.ar
                    beatmap.difficulty_rating = beatmap_data.difficulty_rating
                    beatmap.mode = beatmap_data.mode

                    beatmap.save()
                    messages.success(request, f"Beatmap {beatmap_id_request} updated.")
                except Exception as e:
                    messages.error(request, f"An error occurred while fetching the beatmap information: {e}")

            context['beatmap'] = beatmap

    if 'beatmap' in context:
        beatmap = context['beatmap']

        # Query for user's tags for this beatmap
        user_tag_applications = TagApplication.objects.filter(
            beatmap=beatmap, user=request.user
        )
        user_tags = [tag_app.tag for tag_app in user_tag_applications]

        # Prepare tags with counts and is_applied_by_user flag
        tags_with_counts = []
        for tag in beatmap.tags.all():
            tag_count = TagApplication.objects.filter(tag=tag).count()
            is_applied_by_user = tag in user_tags
            tags_with_counts.append({
                'name': tag.name,
                'apply_count': tag_count,
                'is_applied_by_user': is_applied_by_user
            })

        context['tags_with_counts'] = tags_with_counts

    return render(request, 'beatmap_info.html', {'beatmap': beatmap})

def beatmap_detail(request, beatmap_id):
    """
    Detailed view of a beatmap with tags and other information.
    """
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Query tags applied to this beatmap
    tags_with_counts = TagApplication.objects.filter(beatmap=beatmap).values('tag__name').annotate(
        apply_count=Count('id')
    ).order_by('-apply_count')

    # Handle tag addition (if applicable)
    if request.method == 'POST' and 'tag_name' in request.POST:
        tag_name = request.POST.get('tag_name')
        # Logic to create a TagApplication for this beatmap and tag

    return render(request, 'beatmap_detail.html', {'beatmap': beatmap, 'tags_with_counts': tags_with_counts})

# --------------------------------------------------------------------- #

# ----------------------------- Tag Views ----------------------------- #

def get_tags(request):
    """
    Retrieve tags for a specific beatmap.
    """
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Fetch all tags for this beatmap with a count of distinct users that applied each tag
    tags_with_user_counts = TagApplication.objects.filter(
        beatmap=beatmap
    ).values('tag__name').annotate(
        apply_count=Count('user', distinct=True)
    ).order_by('tag__name')

    # Fetch all TagApplication instances for the current user and this beatmap
    user_tag_names = set(TagApplication.objects.filter(
        user=user, beatmap=beatmap
    ).values_list('tag__name', flat=True))

    # Construct the list of dictionaries
    tags_with_counts_list = [
        {
            'name': tag['tag__name'],
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
    ).values('name', 'beatmap_count')
    return JsonResponse(list(tags), safe=False)


@login_required
def modify_tag(request):
    """
    Apply or remove a tag for a beatmap by the current user.
    """
    if request.method == 'POST':
        tag_name = request.POST.get('tag')
        beatmap_id = request.POST.get('beatmap_id')
        user = request.user

        # Create the tag if it doesn't exist
        tag, _ = Tag.objects.get_or_create(name=tag_name)
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
            return JsonResponse({'status': 'success', 'action': 'removed'})

        # If created, a new tag application was made
        return JsonResponse({'status': 'success', 'action': 'applied'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

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

def search_results(request):
    """
    Handle beatmap search queries and display results.
    """
    query = request.GET.get('query', '').strip()
    selected_mode = request.GET.get('mode', '').strip()

    # If query is empty, return an empty context or a message
    if not query:
        context = {
            'beatmaps': Beatmap.objects.none(),  # No results if no query
            'query': query,
            'message': 'Please enter a search term.',
        }
        return render(request, 'search_results.html', context)

    # Initialize the beatmaps queryset and filter by mode if selected
    beatmaps = Beatmap.objects.all()
    if selected_mode:
        beatmaps = beatmaps.filter(mode=selected_mode)

    if query:
        # Use regular expression to split the query into terms, treating quoted strings as single terms
        search_terms = re.findall(r'"[^"]+"|[^"\s]+', query)

        for term in search_terms:
            if '=' in term:
                # Handle attribute=value queries
                attribute, value = term.split('=', 1)
                attribute = attribute.upper().strip()
                value = value.strip()

                if attribute == 'AR':
                    beatmaps = beatmaps.filter(Q(ar__exact=value))
                elif attribute == 'CS':
                    beatmaps = beatmaps.filter(Q(cs__exact=value))
                elif attribute == 'BPM':
                    beatmaps = beatmaps.filter(Q(bpm__exact=value))
                elif attribute == 'OD':
                    beatmaps = beatmaps.filter(Q(accuracy__exact=value))

            elif '>' in term or '<' in term:
                # Handle attribute>value or attribute<value queries
                attribute, value = re.split(r'[><=]', term)
                attribute = attribute.upper().strip()
                value = value.strip()

                if '>' in term:
                    if term.startswith('>='):
                        lookup = 'gte'
                    else:
                        lookup = 'gt'
                elif '<' in term:
                    if term.startswith('<='):
                        lookup = 'lte'
                    else:
                        lookup = 'lt'

                if attribute == 'AR':
                    beatmaps = beatmaps.filter(**{f'ar__{lookup}': value})
                elif attribute == 'CS':
                    beatmaps = beatmaps.filter(**{f'cs__{lookup}': value})
                elif attribute == 'BPM':
                    beatmaps = beatmaps.filter(**{f'bpm__{lookup}': value})
                elif attribute == 'OD':
                    beatmaps = beatmaps.filter(**{f'accuracy__{lookup}': value})

            elif term.startswith('-"') and term.endswith('"') or term.startswith('-'):
                # Handle exclusion terms
                exclude_term = term.strip('-"')
                beatmaps = beatmaps.exclude(
                    Q(tags__name__iexact=exclude_term) |
                    Q(title__icontains=exclude_term) |
                    Q(creator__icontains=exclude_term) |
                    Q(artist__icontains=exclude_term) |
                    Q(version__icontains=exclude_term)
                )
            else:
                # Handle inclusion terms
                include_term = term.strip('"')
                beatmaps = beatmaps.filter(
                    Q(tags__name__iexact=include_term) |
                    Q(title__icontains=include_term) |
                    Q(creator__icontains=include_term) |
                    Q(artist__icontains=include_term) |
                    Q(version__icontains=include_term) |
                    Q(total_length__icontains=include_term) |
                    Q(drain__icontains=include_term) |
                    Q(accuracy__icontains=include_term) |
                    Q(difficulty_rating__icontains=include_term) |
                    Q(mode__iexact=selected_mode)
                )

        # Annotate and order by the number of tags
        beatmaps = beatmaps.annotate(
            num_tags=Count('tags__tagapplication', distinct=True)
        ).order_by('-num_tags')
    else:
        beatmaps = Beatmap.objects.none()

    return render(request, 'search_results.html', {'beatmaps': beatmaps})

# ------------------------------------------------------------------------ #

# ----------------------------- Settings View ----------------------------- #

@login_required
def settings(request):
    """User settings view for managing API keys."""
    # Fetch all API keys associated with the current user
    api_keys = CustomAPIKey.objects.filter(user=request.user)

    full_key = None

    if request.method == "POST":
        if 'generate_key' in request.POST:
            try:
                # Generate a new API key
                print(f'{request.user.username}')  # This does print the username so it isn't empty
                api_key, key = CustomAPIKey.objects.create_key(name=request.user.username, user=request.user)
                full_key = key  # Store the full key to display it once
                messages.success(request, 'API Key generated successfully.')
            except IntegrityError:
                messages.error(request, 'Failed to generate API Key. Please try again.')
        elif 'key_name' in request.POST:
            # Handle renaming of API key
            api_key_id = request.POST.get('api_key_id')
            new_name = request.POST.get('key_name', '').strip()
            if not api_key_id:
                messages.error(request, 'API Key ID is missing.')
            elif not new_name:
                messages.error(request, 'API Key name cannot be empty.')
            else:
                try:
                    api_key = CustomAPIKey.objects.get(id=api_key_id, user=request.user)
                    api_key.key_name = new_name
                    api_key.save()
                    messages.success(request, 'API Key name updated successfully.')
                except CustomAPIKey.DoesNotExist:
                    messages.error(request, 'API Key not found.')
                except IntegrityError:
                    messages.error(request, 'Failed to update API Key name. Please try again.')
            return redirect('settings')  # Redirect to prevent form resubmission
        elif 'delete_key' in request.POST:
            # Handle deletion of API key
            api_key_id = request.POST.get('api_key_id')
            if not api_key_id:
                messages.error(request, 'API Key ID is missing.')
            else:
                try:
                    api_key = CustomAPIKey.objects.get(id=api_key_id, user=request.user)
                    api_key.delete()
                    messages.success(request, 'API Key deleted successfully.')
                except CustomAPIKey.DoesNotExist:
                    messages.error(request, 'API Key not found.')
                except IntegrityError:
                    messages.error(request, 'Failed to delete API Key. Please try again.')
            return redirect('settings')  # Redirect to prevent form resubmission

    return render(request, 'settings.html', {
        'api_keys': api_keys,
        'full_key': full_key,
    })


from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

# Import your models
# from .models import TagApplication, APIKey, UserProfile, etc.

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
    tags = Tag.objects.annotate(total=Count('tagapplication')).filter(total__gt=0).order_by('-total')[:50]

    # Prepare tags for display
    if user and user.is_authenticated:
        user_tag_ids = TagApplication.objects.filter(user=user).values_list('tag_id', flat=True)
        for tag in tags:
            tag.is_applied_by_user = tag.id in user_tag_ids
    else:
        for tag in tags:
            tag.is_applied_by_user = False

    return tags

def get_recommendations(user=None):
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
            ).order_by('-total_tags').distinct()[:5]
        else:
            # User hasn't tagged anything yet; provide 5 random maps
            recommended_maps = Beatmap.objects.annotate(
                total_tags=Count('tagapplication')
            ).filter(
                total_tags__gt=0
            ).order_by('?')[:5]
    else:
        # For anonymous users, provide 5 random maps
        recommended_maps = Beatmap.objects.annotate(
            total_tags=Count('tagapplication')
        ).filter(
            total_tags__gt=0
        ).order_by('?')[:5]

    return recommended_maps



def home(request):
    user = request.user if request.user.is_authenticated else None

    # Fetch top tags and recommendations
    tags = get_top_tags(user)
    recommended_maps = get_recommendations(user)

    context = {
        'tags': tags,
        'recommended_maps': recommended_maps,
    }
    return render(request, 'home.html', context)



# ------------------------------------------------------------------------ #

# ----------------------------- API Views ----------------------------- #

from rest_framework_api_key.permissions import HasAPIKey

@api_view(['GET'])
@permission_classes([HasAPIKey])
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


# ------------------------------------------------------------------------ #

# ----------------------------- API ViewSets ----------------------------- #

class BeatmapViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for Beatmap model.
    """
    queryset = Beatmap.objects.all()
    serializer_class = BeatmapSerializer
    permission_classes = [HasAPIKey]  # Require only API key

    @action(detail=False, methods=['get'])
    def filtered(self, request):
        """
        Custom action to filter beatmaps by title.
        """
        query = request.GET.get('query', '')
        beatmaps = Beatmap.objects.filter(title__icontains=query)
        serializer = self.get_serializer(beatmaps, many=True)
        return Response(serializer.data)


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for Tag model.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [HasAPIKey]  # Require only API key


class TagApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for TagApplication model.
    """
    queryset = TagApplication.objects.all()
    serializer_class = TagApplicationSerializer
    permission_classes = [HasAPIKey]  # Require only API key


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for UserProfile model.
    """
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [HasAPIKey]  # Require only API key

# ------------------------------------------------------------------------ #
