# echosu/views/home.py
'''
Homepage, about page, tag-library view, and recommendation helpers.

Imports are grouped, duplicates removed, and string literals switched to
single quotes where practical. Function bodies are untouched aside from
those cosmetic quote changes; overall behaviour is identical.
'''

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import logging
import re
from collections import defaultdict

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.template.loader import render_to_string

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..fetch_genre import fetch_genres, get_or_create_genres
from ..models import Beatmap, Genre, Tag, TagApplication
from .auth import api, logger
from .beatmap import join_diff_creators, GAME_MODE_MAPPING
from .shared import GAME_MODE_MAPPING


# ---------------------------------------------------------------------------
# Simple page views
# ---------------------------------------------------------------------------

def home_simple(request):
    '''Legacy no-logic home view; kept for backward compatibility.'''
    return render(request, 'home.html')


def about(request):
    '''Render the about page.'''
    return render(request, 'about.html')


def admin(request):
    '''Redirect to the admin panel.'''
    return redirect('/admin/')


def error_page_view(request):
    '''Render the generic error page.'''
    return render(request, 'error_page.html')


def tag_library(request):
    '''Alphabetical list of all tags with beatmap counts.'''
    tags = Tag.objects.annotate(beatmap_count=Count('beatmaps')).order_by('name')
    return render(request, 'tag_library.html', {'tags': tags})


def custom_404_view(request, exception):
    return render(request, '404.html', status=404)

# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def get_top_tags(user=None):
    '''Return the 50 most‑used tags, marking which ones the user applied.'''
    tags = (
        Tag.objects
        .annotate(total=Count('tagapplication'))
        .filter(total__gt=0)
        .order_by('-total')
        .select_related('description_author')[:50]
    )

    if user and user.is_authenticated:
        user_tag_ids = set(
            TagApplication.objects.filter(user=user).values_list('tag_id', flat=True)
        )
        for tag in tags:
            tag.is_applied_by_user = tag.id in user_tag_ids
    else:
        for tag in tags:
            tag.is_applied_by_user = False

    return tags


# ---------------------------------------------------------------------------
# Recommendation helpers
# ---------------------------------------------------------------------------

def annotate_beatmaps_with_tags(beatmaps, user):
    '''Attach ``beatmap.tags_with_counts`` list for UI display.'''
    beatmap_ids = beatmaps.values_list('id', flat=True)
    tag_apps = (
        TagApplication.objects
        .filter(beatmap_id__in=beatmap_ids)
        .select_related('tag')
    )

    beatmap_tag_counts = defaultdict(lambda: defaultdict(int))
    user_applied_tags = defaultdict(set)

    for ta in tag_apps:
        bid, tag = ta.beatmap_id, ta.tag
        beatmap_tag_counts[bid][tag] += 1
        if user and user.is_authenticated and ta.user_id == user.id:
            user_applied_tags[bid].add(tag)

    for bm in beatmaps:
        tlist = []
        for tag, count in beatmap_tag_counts.get(bm.id, {}).items():
            tlist.append({
                'tag': tag,
                'apply_count': count,
                'is_applied_by_user': tag in user_applied_tags.get(bm.id, set()),
            })
        bm.tags_with_counts = sorted(tlist, key=lambda x: -x['apply_count'])

    return beatmaps


def get_recommendations(user=None, limit=5, offset=0):
    '''Return a queryset of recommended beatmaps.'''
    qs = Beatmap.objects.annotate(total_tags=Count('tagapplication')).filter(total_tags__gt=0)

    if user and user.is_authenticated:
        user_tags = list(
            TagApplication.objects.filter(user=user).values_list('tag_id', flat=True)
        )
        if user_tags:
            tagged = TagApplication.objects.filter(user=user).values_list('beatmap_id', flat=True)
            qs = (
                qs.filter(tagapplication__tag_id__in=user_tags)
                .exclude(id__in=tagged)
                .order_by('-total_tags')
            )
        else:
            qs = qs.order_by('?')
    else:
        qs = qs.order_by('?')

    return annotate_beatmaps_with_tags(qs[offset:offset + limit], user)


# ---------------------------------------------------------------------------
# AJAX / partial views
# ---------------------------------------------------------------------------

def load_more_recommendations(request):
    '''Return additional recommended maps via AJAX.'''
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    user = request.user if request.user.is_authenticated else None
    offset = int(request.GET.get('offset', 0))
    limit = int(request.GET.get('limit', 5))

    maps = get_recommendations(user=user, limit=limit, offset=offset)
    html = render_to_string('partials/recommended_maps.html', {'recommended_maps': maps}, request)

    return JsonResponse({'rendered_maps': html})


# ---------------------------------------------------------------------------
# Full home view (search / beatmap form handling)
# ---------------------------------------------------------------------------

def home(request):
    '''Full-featured home page with tag cloud and recommendations.'''
    user = request.user if request.user.is_authenticated else None

    context = {
        'tags': get_top_tags(user),
        'recommended_maps': get_recommendations(user),
    }

    if request.method == 'POST':
        beatmap_input = request.POST.get('beatmap_id', '').strip()
        if beatmap_input:
            try:
                match = re.search(r'(\d+)$', beatmap_input)
                if not match:
                    raise ValueError('Invalid input. Provide a beatmap link or ID.')

                bid = match.group(1)
                bm_data = api.beatmap(bid)
                if not bm_data:
                    raise ValueError(f"{bid} isn't a valid beatmap ID.")

                beatmap, created = Beatmap.objects.get_or_create(beatmap_id=bid)
                if created:
                    if hasattr(bm_data, '_beatmapset'):
                        bms = bm_data._beatmapset
                        beatmap.beatmapset_id = getattr(bms, 'id', beatmap.beatmapset_id)
                        beatmap.title = getattr(bms, 'title', beatmap.title)
                        beatmap.artist = getattr(bms, 'artist', beatmap.artist)
                        beatmap.creator = join_diff_creators(bm_data)
                        beatmap.favourite_count = getattr(bms, 'favourite_count', beatmap.favourite_count)
                        beatmap.cover_image_url = getattr(getattr(bms, 'covers', {}), 'cover_2x', beatmap.cover_image_url)

                    status_map = {
                        -2: 'Graveyard',
                        -1: 'WIP',
                        0: 'Pending',
                        1: 'Ranked',
                        2: 'Approved',
                        3: 'Qualified',
                        4: 'Loved',
                    }

                    beatmap.version = getattr(bm_data, 'version', beatmap.version)
                    beatmap.total_length = getattr(bm_data, 'total_length', beatmap.total_length)
                    beatmap.bpm = getattr(bm_data, 'bpm', beatmap.bpm)
                    beatmap.cs = getattr(bm_data, 'cs', beatmap.cs)
                    beatmap.drain = getattr(bm_data, 'drain', beatmap.drain)
                    beatmap.accuracy = getattr(bm_data, 'accuracy', beatmap.accuracy)
                    beatmap.ar = getattr(bm_data, 'ar', beatmap.ar)
                    beatmap.difficulty_rating = getattr(bm_data, 'difficulty_rating', beatmap.difficulty_rating)
                    beatmap.status = status_map.get(bm_data.status.value, 'Unknown')
                    api_mode = getattr(bm_data, 'mode', beatmap.mode)
                    beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode), 'unknown')
                    beatmap.playcount = getattr(bm_data, 'playcount', beatmap.playcount)
                    beatmap.save()

                    genres = fetch_genres(beatmap.artist, beatmap.title)
                    if genres:
                        beatmap.genres.set(get_or_create_genres(genres))

                context['beatmap'] = beatmap
            except Exception as exc:
                msg = f'Error: {exc}'
                messages.error(request, msg)
                logger.error(f"Error processing beatmap input '{beatmap_input}': {exc}")

    else:
        bid = request.GET.get('beatmap_id')
        if bid:
            beatmap = get_object_or_404(Beatmap, beatmap_id=bid)
            context['beatmap'] = beatmap

    if 'beatmap' in context:
        beatmap = context['beatmap']
        tags = (
            TagApplication.objects
            .filter(beatmap=beatmap)
            .values('tag__id', 'tag__name', 'tag__description', 'tag__description_author__username')
            .annotate(apply_count=Count('id'))
            .order_by('-apply_count')
        )
        if request.user.is_authenticated:
            user_tag_ids = set(
                TagApplication.objects.filter(beatmap=beatmap, user=request.user).values_list('tag__id', flat=True)
            )
        else:
            user_tag_ids = set()

        for t in tags:
            t['is_applied_by_user'] = t['tag__id'] in user_tag_ids
        context['beatmap_tags_with_counts'] = tags

    return render(request, 'home.html', context)
