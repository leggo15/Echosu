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
from .beatmap import join_diff_creators
from .shared import (
    GAME_MODE_MAPPING,
    compute_attribute_windows,
    derive_filters_from_tags,
    build_similar_maps_query,
)
from ..helpers.rosu_utils import get_or_compute_pp


def about(request):
    '''Render the about page.'''
    return render(request, 'about.html')


def admin(request):
    '''Redirect to the admin panel.'''
    return redirect('/admin/')


def tag_library(request):
    '''Alphabetical list of all tags with beatmap counts, plus top 50 by usage, and a contributors leaderboard.'''
    tags = (
        Tag.objects
        .select_related('description_author')
        .annotate(
            beatmap_count=Count('tagapplication__beatmap', filter=Q(tagapplication__true_negative=False), distinct=True),
            description_author_username=F('description_author__username'),
        )
        .order_by('name')
    )

    top_tags = (
        Tag.objects
        .select_related('description_author')
        .annotate(
            map_count=Count('tagapplication__beatmap', filter=Q(tagapplication__true_negative=False), distinct=True),
            description_author_username=F('description_author__username'),
        )
        .filter(map_count__gt=0)
        .order_by('-map_count', 'name')[:50]
    )

    # Contributors leaderboard: total number of user tag applications per user (exclude predictions / null users)
    leaderboard_qs = TagApplication.objects.filter(user__isnull=False)
    leaderboard = (
        leaderboard_qs
        .values('user__username')
        .annotate(
            tag_count=Count('id'),
            unique_maps=Count('beatmap', distinct=True),
        )
        .order_by('-tag_count', 'user__username')[:100]
    )

    current_user_stats = None
    if request.user.is_authenticated:
        current_user_stats = (
            TagApplication.objects
            .filter(user=request.user)
            .aggregate(
                tag_count=Count('id'),
                unique_maps=Count('beatmap', distinct=True),
            )
        )
        current_user_stats['username'] = request.user.username

    context = {
        'tags': tags,
        'top_tags': top_tags,
        'leaderboard': leaderboard,
        'current_user_stats': current_user_stats,
    }

    return render(request, 'tag_library.html', context)
