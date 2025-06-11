# echosu/views/home.py

# Standard library imports
import re
from collections import defaultdict
import logging

# Django imports
from django.contrib import messages
from django.db.models import Count, F, FloatField, Q 
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
# Local application imports
from ..models import Beatmap, Tag, TagApplication, Genre
from ..fetch_genre import fetch_genres, get_or_create_genres
from .auth import api
from .beatmap import join_diff_creators, GAME_MODE_MAPPING

# Set up a logger for this module
logger = logging.getLogger(__name__)
# ----------------------------- Constants ----------------------------- #

GAME_MODE_MAPPING = {
    'GameMode.OSU': 'osu',
    'GameMode.TAIKO': 'taiko',
    'GameMode.CATCH': 'fruits',
    'GameMode.MANIA': 'mania',
}


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

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)


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
from ..models import Genre
from ..fetch_genre import fetch_genres, get_or_create_genres 


def home(request):
    user = request.user if request.user.is_authenticated else None

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

                    if created:
                        # Update beatmap attributes from the API data
                        if hasattr(beatmap_data, '_beatmapset'):
                            beatmapset = beatmap_data._beatmapset
                            beatmap.beatmapset_id = getattr(beatmapset, 'id', beatmap.beatmapset_id)
                            beatmap.title = getattr(beatmapset, 'title', beatmap.title)
                            beatmap.artist = getattr(beatmapset, 'artist', beatmap.artist)
                            beatmap.creator = join_diff_creators(beatmap_data)
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
