# echosu/views/beatmap.py
"""Beatmap detail and update views.

Only the import section is reorganised—no functional changes were made.
Imports now follow *standard-lib → Django → local* order and duplicates
were removed.
"""

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import logging

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, TagApplication
from ..fetch_genre import fetch_genres, get_or_create_genres  # genre helpers
from .auth import api  # shared Ossapi instance
from .secrets import redirect_uri, logger
from .shared import GAME_MODE_MAPPING

# ---------------------------------------------------------------------------
# Beatmap views
# ---------------------------------------------------------------------------

def beatmap_detail(request, beatmap_id):
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Get TagApplications for this beatmap
    tag_apps = TagApplication.objects.filter(beatmap=beatmap).select_related('tag')

    # Annotate tags with apply counts
    tags_with_counts = tag_apps.values(
        'tag__id', 'tag__name', 'tag__description', 'tag__description_author'
    ).annotate(apply_count=Count('id')).order_by('-apply_count')

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
            'is_applied_by_user': tag['tag__id'] in user_applied_tags,
        }
        for tag in tags_with_counts
    ]

    # Prepare tags_query_string for "Find Similar Maps" link
    top_N = 10
    top_tags = [tag['tag__name'] for tag in tags_with_counts[:top_N] if tag['tag__name']]
    encapsulated_tags = [f'"{tag}"' if ' ' in tag else tag for tag in top_tags]
    tags_query_string = ' '.join(encapsulated_tags)

    # Calculate star_min and star_max based on current beatmap's star rating
    current_star = beatmap.difficulty_rating
    star_min = max(0, current_star - 0.6)
    star_max = min(15, current_star + 0.6)

    # Calculate bpm_min and bpm_max based on current beatmap's bpm
    current_bpm = beatmap.bpm
    bpm_min = current_bpm - 10
    bpm_max = current_bpm + 10

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


def join_diff_creators(bm):
    """Return a comma-separated list of all mappers for this difficulty."""
    owners = getattr(bm, 'owners', None) or getattr(bm, '_owners', None) or []
    names, seen = [], set()
    for o in owners:
        if o.id not in seen:
            names.append(o.username)
            seen.add(o.id)

    if not names:
        diff_uid = getattr(bm, 'user_id', None)
        set_uid = bm._beatmapset.user_id
        if diff_uid and diff_uid != set_uid:
            guest_name = (
                getattr(getattr(bm, 'user', None), 'username', None) or str(diff_uid)
            )
            names.append(guest_name)
            seen.add(diff_uid)

    if bm._beatmapset.user_id not in seen:
        names.append(bm._beatmapset.creator)

    return ', '.join(names)


@require_POST

def update_beatmap_info(request):
    beatmap_id = request.POST.get('beatmap_id')
    status_mapping = {
        -2: 'Graveyard',
        -1: 'WIP',
        0: 'Pending',
        1: 'Ranked',
        2: 'Approved',
        3: 'Qualified',
        4: 'Loved',
    }

    try:
        beatmap_data = api.beatmap(beatmap_id)
        if not beatmap_data:
            logger.warning(f'Beatmap ID {beatmap_id} not found in osu! API.')
            return JsonResponse({'error': 'Beatmap not found in osu! API.'}, status=404)

        beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)
        logger.info(
            f"{'Created new' if created else 'Updating existing'} Beatmap with ID: {beatmap_id}"
        )

        beatmap.title = beatmap_data._beatmapset.title
        beatmap.artist = beatmap_data._beatmapset.artist
        beatmap.creator = join_diff_creators(beatmap_data)
        beatmap.cover_image_url = getattr(
            beatmap_data._beatmapset.covers, 'cover_2x', None
        )
        beatmap.total_length = beatmap_data.total_length
        beatmap.bpm = beatmap_data.bpm
        beatmap.cs = beatmap_data.cs
        beatmap.drain = beatmap_data.drain
        beatmap.accuracy = beatmap_data.accuracy
        beatmap.ar = beatmap_data.ar
        beatmap.difficulty_rating = beatmap_data.difficulty_rating
        beatmap.status = status_mapping.get(beatmap_data.status.value, 'Unknown')
        beatmap.playcount = beatmap_data.playcount
        beatmap.favourite_count = getattr(beatmap_data._beatmapset, 'favourite_count', 0)

        api_mode_value = getattr(beatmap_data, 'mode', beatmap.mode)
        beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode_value), 'unknown')

        beatmap.save()
        logger.info(f'Saved Beatmap with ID: {beatmap_id}')

        genres = fetch_genres(beatmap.artist, beatmap.title)
        logger.debug(f"Fetched genres for Beatmap '{beatmap_id}': {genres}")

        if genres:
            genre_objects = get_or_create_genres(genres)
            beatmap.genres.set(genre_objects)
            logger.info(f"Associated genres {genres} with Beatmap '{beatmap_id}'.")
        else:
            logger.info(
                f"No genres found for Beatmap '{beatmap_id}'. Clearing existing genres."
            )
            beatmap.genres.clear()

        return JsonResponse({'message': 'Beatmap info updated successfully.'})

    except Exception as e:
        logger.error(f"Error updating Beatmap '{beatmap_id}': {e}")
        return JsonResponse({'error': str(e)}, status=500)
