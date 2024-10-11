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
from .models import Beatmap, Tag, TagApplication, UserProfile  # Used in multiple views
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
    if osu_id in ("4978940", "9396661"):
        user.is_superuser = True
        user.is_staff = True
        user.save()

    # Authenticate and log in the user
    user.backend = 'django.contrib.auth.backends.ModelBackend'  # Set backend manually
    login(request, user)

    # Store osu_id in session for future use
    request.session['osu_id'] = osu_id

    # Generate or retrieve the token for the user
    token, _ = Token.objects.get_or_create(user=user)
    # Optionally, you can store the token key in the session or display it to the user

    # views.py

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

# ----------------------------- Home and Admin Views ----------------------------- #

def home(request):
    """Render the home page."""
    return render(request, 'home.html')


def admin(request):
    """Redirect to the admin panel."""
    return redirect('/admin/')

# ------------------------------------------------------------------------ #

# ----------------------------- Beatmap Detail Views ----------------------------- #

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
    Retrieve tags for a specific beatmap
    """
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Fetch all tags for this beatmap with a count of distinct users that applied each tag
    tags_with_user_counts = TagApplication.objects.filter(
        beatmap=beatmap
    ).values('tag__name').annotate(
        apply_count=Count('user', distinct=True)
    ).order_by('-apply_count')

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
    ).values('name', 'beatmap_count').order_by('-beatmap_count')
    return JsonResponse(list(tags), safe=False)


from better_profanity import profanity

# Define the allowed tag pattern if not already defined
ALLOWED_TAG_PATTERN = re.compile(r'^[A-Za-z0-9 _-]{1,100}$')

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

        # Trim leading and trailing spaces
        processed_tag = tag_name.strip()

        # Convert to lowercase
        processed_tag = processed_tag.lower()

        # Disallow specific chars and set max length
        if not ALLOWED_TAG_PATTERN.match(processed_tag):
            error_message = 'Tag must be 1-100 characters long and can only contain letters, numbers, spaces, hyphens, and underscores.'
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
from django.db.models import Q, Count, Case, When, Value, BooleanField, IntegerField
from django.db.models import Prefetch
from django.core.paginator import Paginator
from django.contrib.auth.models import User
import re
from collections import defaultdict
from nltk.stem import PorterStemmer

stemmer = PorterStemmer()

def stem_word(word):
    return stemmer.stem(word)

def search_results(request):
    """
    Handle beatmap search queries and display results focused on tag searches with pagination and sorted tags.
    """
    query = request.GET.get('query', '').strip()
    selected_mode = request.GET.get('mode', '').strip()

    # If query is empty, return an empty context or a message
    if not query:
        context = {
            'beatmaps': Paginator(Beatmap.objects.none(), 10).page(1),  # Empty page
            'query': query,
            'message': 'Please enter a search term.',
        }
        return render(request, 'search_results.html', context)

    # Initialize the beatmaps queryset and filter by mode if selected (case-insensitive)
    beatmaps = Beatmap.objects.all()
    if selected_mode:
        beatmaps = beatmaps.filter(mode__iexact=selected_mode)

    # Parse the query into search terms
    search_terms = parse_search_terms(query)

    # Build inclusion and exclusion Q objects and get include_tag_names
    beatmaps, include_tag_names = build_query_conditions(beatmaps, search_terms)

    # Annotate beatmaps with the sum of counts of TagApplications for the searched tags
    if include_tag_names:
        beatmaps = beatmaps.annotate(
            priority=Count('tagapplication', filter=Q(tagapplication__tag__name__in=include_tag_names))
        ).order_by('-priority')
    else:
        # Default ordering if no specific tags are searched
        beatmaps = beatmaps.annotate(
            priority=Value(0, IntegerField())
        ).order_by('-priority')

    # Implement pagination
    paginator = Paginator(beatmaps, 10)  # Show 10 beatmaps per page
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.get_page(page_number)
    except:
        page_obj = paginator.get_page(1)  # Default to page 1 if invalid

    # Annotate beatmaps on the current page
    annotate_beatmaps_with_tags(page_obj.object_list, request.user)

    context = {
        'beatmaps': page_obj,
        'query': query,
    }

    return render(request, 'search_results.html', context)



#######################################################################################

from collections import defaultdict

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
    return re.findall(r'-?"[^"]+"|-?[^"\s]+', query)

#######################################################################################

def is_exclusion_term(term):
    return term.startswith('-')

#######################################################################################

def build_query_conditions(beatmaps, search_terms):
    """
    Build inclusion and exclusion Q objects based on the search terms.
    """
    include_q = Q()
    exclude_q = Q()
    include_tag_names = set()
    exclude_tag_names = set()

    for term in search_terms:
        term = term.strip()
        # Handle attribute=value queries
        if is_attribute_equal_query(term):
            beatmaps = handle_attribute_equal_query(beatmaps, term)
        elif is_attribute_comparison_query(term):
            beatmaps = handle_attribute_comparison_query(beatmaps, term)
        elif is_exclusion_term(term):
            exclude_term = term.lstrip('-').strip('"').strip()
            # Fuzzy match tags
            matching_tags = Tag.objects.filter(name__icontains=exclude_term)
            if matching_tags.exists():
                exclude_tag_names.update([tag.name for tag in matching_tags])
            else:
                exclude_q |= build_exclusion_q(exclude_term)
        else:
            include_term = term.strip('"').strip()
            # Fuzzy match tags
            matching_tags = Tag.objects.filter(name__icontains=include_term)
            if matching_tags.exists():
                include_tag_names.update([tag.name for tag in matching_tags])
            else:
                include_q &= build_inclusion_q(include_term)

    # Apply inclusion filters
    if include_q:
        beatmaps = beatmaps.filter(include_q)

    # Apply exclusion filters
    if exclude_q:
        beatmaps = beatmaps.exclude(exclude_q)

    # Apply tag exclusion filters
    if exclude_tag_names:
        beatmaps = beatmaps.exclude(tags__name__in=exclude_tag_names)

    # Apply tag inclusion filters
    # Fetch all beatmaps with at least one of the matching tags
    # but only for the tags part of the search
    if include_tag_names:
        beatmaps = beatmaps.filter(tags__name__in=include_tag_names).distinct()

    return beatmaps, include_tag_names



#######################################################################################

def is_attribute_equal_query(term):
    return '=' in term and not any(op in term for op in ['>=', '<=', '>', '<'])

#######################################################################################

def is_attribute_comparison_query(term):
    return any(op in term for op in ['>=', '<=', '>', '<'])

#######################################################################################

def handle_attribute_equal_query(beatmaps, term):
    attribute, value = term.split('=', 1)
    attribute = attribute.upper().strip()
    value = value.strip()

    # Map attribute to field name
    field_map = {
        'AR': 'ar',
        'CS': 'cs',
        'BPM': 'bpm',
        'OD': 'accuracy',
    }

    field_name = field_map.get(attribute)
    if field_name:
        try:
            numeric_value = float(value)
            filter_key = f'{field_name}'
            beatmaps = beatmaps.filter(**{filter_key: numeric_value})
        except ValueError:
            pass  # Handle invalid float conversion if necessary
    return beatmaps

#######################################################################################

def handle_attribute_comparison_query(beatmaps, term):
    # Handle attribute comparison queries
    match = re.match(r'(AR|CS|BPM|OD)(>=|<=|>|<)(\d+(\.\d+)?)', term, re.IGNORECASE)
    if match:
        attribute, operator, value, _ = match.groups()
        attribute = attribute.upper().strip()
        lookup_map = {
            '>': 'gt',
            '<': 'lt',
            '>=': 'gte',
            '<=': 'lte',
        }
        lookup = lookup_map.get(operator)
        field_map = {
            'AR': 'ar',
            'CS': 'cs',
            'BPM': 'bpm',
            'OD': 'accuracy',
        }
        field_name = field_map.get(attribute)
        if lookup and field_name:
            try:
                numeric_value = float(value)
                filter_key = f'{field_name}__{lookup}'
                beatmaps = beatmaps.filter(**{filter_key: numeric_value})
            except ValueError:
                pass  # Handle invalid float conversion if necessary
    return beatmaps

#######################################################################################

def build_exclusion_q(term):
    # Handle exclusion terms
    exclude_term = term.lstrip('-').strip('"').strip()
    # Apply stemming to the exclude term
    stem_exclude_term = stem_word(exclude_term.lower())
    return Q(
        Q(tags__name__iexact=exclude_term) |
        Q(title__icontains=exclude_term) |
        Q(creator__icontains=exclude_term) |
        Q(artist__icontains=exclude_term) |
        Q(version__icontains=exclude_term)
    )

#######################################################################################

def build_inclusion_q(term):
    # Handle inclusion terms
    include_term = term.strip('"').strip()
    # Apply stemming to the include term
    stem_include_term = stem_word(include_term.lower())
    return Q(
        Q(tags__name__iexact=include_term) |
        Q(title__icontains=include_term) |
        Q(creator__icontains=include_term) |
        Q(artist__icontains=include_term) |
        Q(version__icontains=include_term) |
        Q(total_length__icontains=include_term) |
        Q(drain__icontains=include_term) |
        Q(accuracy__icontains=include_term) |
        Q(difficulty_rating__icontains=include_term)
    )



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

    # Handle beatmap info form submission (POST request)
    if request.method == 'POST':
        beatmap_id_request = request.POST.get('beatmap_id')
        if beatmap_id_request:
            try:
                # Attempt to fetch beatmap data from the osu! API
                beatmap_data = api.beatmap(beatmap_id_request)
                
                if not beatmap_data:
                    # If no data is returned, the beatmap ID is invalid
                    raise ValueError(f"{beatmap_id_request} isn't a valid beatmap ID.")

                # Get or create the beatmap object in the database
                beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id_request)

                # Check if beatmap data needs to be updated
                if created or any(
                    attr is None for attr in [
                        beatmap.title, beatmap.version, beatmap.artist, beatmap.creator,
                        beatmap.cover_image_url, beatmap.total_length, beatmap.bpm,
                        beatmap.cs, beatmap.drain, beatmap.accuracy, beatmap.ar,
                        beatmap.difficulty_rating, beatmap.mode, beatmap.beatmapset_id
                    ]
                ):
                    # Update beatmap attributes from the API data
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

                    # Save the updated beatmap to the database
                    beatmap.save()

                # Add the beatmap to the context to display its information
                context['beatmap'] = beatmap

            except Exception as e:
                context['error'] = f'{beatmap_id_request} is not a valid beatmap ID.'
    else:
        beatmap_id = request.GET.get('beatmap_id')
        if beatmap_id:
            beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)
            context['beatmap'] = beatmap

    # If a beatmap is in context, prepare tags
    if 'beatmap' in context:
        beatmap = context['beatmap']

        # Query for user's tags for this beatmap
        user_tag_applications = TagApplication.objects.filter(
            beatmap=beatmap, user=request.user
        )
        user_tags = [tag_app.tag for tag_app in user_tag_applications]

        # Prepare tags with counts and is_applied_by_user flag
        beatmap_tags_with_counts = []
        for tag in beatmap.tags.all():
            tag_count = TagApplication.objects.filter(tag=tag, beatmap=beatmap).count()
            is_applied_by_user = tag in user_tags
            beatmap_tags_with_counts.append({
                'name': tag.name,
                'apply_count': tag_count,
                'is_applied_by_user': is_applied_by_user
            })

        context['beatmap_tags_with_counts'] = beatmap_tags_with_counts

    return render(request, 'home.html', context)




# ------------------------------------------------------------------------ #

# ----------------------------- API Views ----------------------------- #

from rest_framework import viewsets
from rest_framework.decorators import api_view, authentication_classes, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count
from .models import Beatmap, Tag, TagApplication, UserProfile
from .serializers import BeatmapSerializer, TagSerializer, TagApplicationSerializer, UserProfileSerializer
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

    @action(detail=False, methods=['get'])
    def filtered(self, request):
        query = request.GET.get('query', '')
        beatmaps = Beatmap.objects.filter(title__icontains=query)
        serializer = self.get_serializer(beatmaps, many=True)
        return Response(serializer.data)


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


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

# ------------------------------------------------------------------------ #
