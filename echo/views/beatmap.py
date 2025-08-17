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
import re

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, TagApplication
from ..fetch_genre import fetch_genres, get_or_create_genres  # genre helpers
from .auth import api  # shared Ossapi instance
from .secrets import redirect_uri, logger
from .shared import (
    GAME_MODE_MAPPING,
    TAG_FILTER_MAPPING,
    compute_attribute_windows,
    derive_filters_from_tags,
    build_similar_maps_query,
    format_length_hms,
)
from ..helpers.rosu_utils import get_or_compute_timeseries, get_or_compute_pp, get_or_compute_modded_pps
from ..helpers.timestamps import consensus_intervals, normalize_intervals
from rest_framework.authtoken.models import Token

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

    # Compute attribute windows once
    windows = compute_attribute_windows(beatmap)

    # Derive which filters to apply based on present tags
    filters_to_apply = derive_filters_from_tags(top_tags)

    # Build the query string and extra params
    similar_query, extra_params = build_similar_maps_query(filters_to_apply, windows, tags_query_string)



    # NOTE: Intentionally avoid computing heavy data (timeseries, PP) synchronously
    # during page render to keep the detail page responsive. The JS graph will
    # fetch the timeseries asynchronously via the JSON endpoint. PP should be
    # precomputed offline or shown only if already cached on the model.
    try:
        beatmap.length_formatted = format_length_hms(beatmap.total_length)
    except Exception:
        pass

    context = {
        'beatmap': beatmap,
        'tags_with_counts': tags_with_counts,
        'tags_query_string': tags_query_string,
        **windows,
        'similar_query': similar_query,
        'similar_extra_params': extra_params,
    }

    # Provide API token for admin users to allow authenticated API test calls
    try:
        if request.user.is_authenticated and getattr(request.user, 'is_staff', False):
            token, _ = Token.objects.get_or_create(user=request.user)
            context['api_auth_token'] = token.key
    except Exception:
        pass

    return render(request, 'beatmap_detail.html', context)


@login_required
@require_GET
def beatmap_timeseries(request, beatmap_id: int):
    """Return cached or computed rosu difficulty time-series for a beatmap.

    Query params:
      - window_s: int seconds for binning (default 1)
      - mods: comma-free acronyms, e.g., "DT", "HR", "EZ", "HT", "FL"; combinations allowed,
              but mutually exclusive groups DT/HT and HR/EZ will be resolved by keeping the last.
    """
    beatmap = get_object_or_404(Beatmap, beatmap_id=str(beatmap_id))
    try:
        window_s = int(request.GET.get("window_s", 1))
    except Exception:
        window_s = 1
    raw_mods = (request.GET.get("mods", "") or "").upper().strip()
    # Normalise mods string: keep only supported DT/HT/HR/EZ/FL; drop incompatible duplicates
    allowed = ["DT", "HT", "HR", "EZ", "FL"]
    mods_out = []
    seen = set()
    for token in [raw_mods[i:i+2] for i in range(0, len(raw_mods), 2) if raw_mods]:
        if token in allowed:
            # enforce mutual exclusion: DT vs HT
            if token == "DT" and "HT" in seen:
                seen.remove("HT")
                mods_out = [m for m in mods_out if m != "HT"]
            if token == "HT" and "DT" in seen:
                seen.remove("DT")
                mods_out = [m for m in mods_out if m != "DT"]
            # HR vs EZ
            if token == "HR" and "EZ" in seen:
                seen.remove("EZ")
                mods_out = [m for m in mods_out if m != "EZ"]
            if token == "EZ" and "HR" in seen:
                seen.remove("HR")
                mods_out = [m for m in mods_out if m != "HR"]
            if token not in seen:
                seen.add(token)
                mods_out.append(token)
    mods_str = "".join(mods_out) or None
    ts = get_or_compute_timeseries(beatmap, window_seconds=window_s, mods=mods_str)
    if ts is None:
        return JsonResponse({"detail": "Timeseries unavailable"}, status=404)
    return JsonResponse(ts, safe=False)


## Removed: tag_timestamps endpoint in favor of consolidated /api/tag-applications include


@require_POST
def save_tag_timestamps(request, beatmap_id: int):
    """Save current user's timestamp intervals for a given tag on a beatmap.

    Body: JSON { tag_id: number, intervals: [[start_s, end_s], ...], version: 1 }
    """
    beatmap = get_object_or_404(Beatmap, beatmap_id=str(beatmap_id))
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required'}, status=401)

    import json
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'detail': 'Invalid JSON'}, status=400)
    tag_id = data.get('tag_id')
    intervals = data.get('intervals') or []
    if not tag_id:
        return JsonResponse({'detail': 'tag_id required'}, status=400)

    # Ensure the user has applied this tag to this beatmap
    try:
        ta = TagApplication.objects.get(beatmap=beatmap, tag_id=tag_id, user=request.user)
    except TagApplication.DoesNotExist:
        return JsonResponse({'detail': 'You must apply this tag before adding timestamps.'}, status=403)

    cleaned = normalize_intervals([(float(s), float(e)) for s, e in intervals], beatmap.total_length)
    ta.timestamp = {'version': 1, 'intervals': cleaned}
    ta.save(update_fields=['timestamp'])
    return JsonResponse({'status': 'ok', 'saved': ta.timestamp})


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


@login_required
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

        # IDs and set-level metadata
        try:
            beatmap.beatmapset_id = getattr(beatmap_data._beatmapset, 'id', beatmap.beatmapset_id)
        except Exception:
            pass
        beatmap.title = beatmap_data._beatmapset.title
        beatmap.artist = beatmap_data._beatmapset.artist
        # Preserve original set owner for permission logic; update displayed creator
        set_owner_name = getattr(beatmap_data._beatmapset, 'creator', None)
        set_owner_id = getattr(beatmap_data._beatmapset, 'user_id', None)
        if not beatmap.original_creator:
            beatmap.original_creator = set_owner_name
        if not getattr(beatmap, 'original_creator_id', None):
            try:
                beatmap.original_creator_id = str(set_owner_id or '')
            except Exception:
                pass
        # Save set owner id for permission checks
        try:
            beatmap.original_creator_id = str(getattr(beatmap_data._beatmapset, 'user_id', '') or '')
        except Exception:
            pass
        # Determine creator display with guest handling rules
        # Rule: If guest difficulties exist, prefer guest mapper(s) unless
        #  - the diff name contains 'collab' (case-insensitive), or
        #  - the set is single-difficulty (no distinct guest owner)
        computed_creator = join_diff_creators(beatmap_data)
        try:
            all_diffs = getattr(beatmap_data._beatmapset, 'beatmaps', []) or []
            num_diffs = len(all_diffs)
            is_single = num_diffs <= 1
            has_guest = False
            collab_current = 'collab' in (getattr(beatmap_data, 'version', '') or '').lower()
            set_owner_name = getattr(beatmap_data._beatmapset, 'creator', None)
            for d in all_diffs:
                diff_uid = getattr(d, 'user_id', None)
                set_uid = getattr(beatmap_data._beatmapset, 'user_id', None)
                if diff_uid and set_uid and diff_uid != set_uid:
                    has_guest = True
                    # If any diff is marked as collab, allow owner display for that diff only
                    ver = (getattr(d, 'version', '') or '').lower()
                    if 'collab' in ver:
                        collab_current = True
            if has_guest and not is_single and not collab_current:
                # Remove set owner from display when guest exists and not a collab or single set
                guest_only = computed_creator
                if set_owner_name and guest_only.endswith(set_owner_name):
                    # Trim trailing ", {owner}" safely
                    suffix = ', ' + set_owner_name
                    if guest_only.endswith(suffix):
                        guest_only = guest_only[: -len(suffix)]
                beatmap.creator = guest_only
                beatmap.listed_owner = guest_only
                beatmap.listed_owner_id = None  # unknown guest id list string at difficulty mix
            else:
                owner_name = set_owner_name or computed_creator
                beatmap.creator = owner_name
                beatmap.listed_owner = owner_name
                # Capture listed owner id as set owner id by default (when assigning display owner as owner)
                try:
                    beatmap.listed_owner_id = str(set_owner_id or '')
                except Exception:
                    pass
        except Exception:
            beatmap.creator = computed_creator
            beatmap.listed_owner = computed_creator
        beatmap.cover_image_url = getattr(
            beatmap_data._beatmapset.covers, 'cover_2x', None
        )
        beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
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
        # Save per-difficulty last updated timestamp
        try:
            beatmap.last_updated = getattr(beatmap_data, 'last_updated', beatmap.last_updated)
        except Exception:
            pass

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


@require_POST
def quick_add_beatmap(request):
    """Create or refresh a beatmap from an ID/link, then redirect to detail.

    Accepts form field `beatmap_input` which can be a numeric ID or a full
    osu! beatmap URL. Extracts the trailing digits as beatmap_id.
    """
    if not request.user.is_authenticated:
        messages.error(request, 'You must be logged in to add a beatmap.')
        return redirect('home')

    raw_input = (request.POST.get('beatmap_input') or '').strip()
    if not raw_input:
        messages.error(request, 'Please enter a beatmap ID or URL.')
        return redirect('home')

    match = re.search(r'(\d+)$', raw_input)
    if not match:
        messages.error(request, 'Invalid input. Provide a beatmap link or ID.')
        return redirect('home')

    beatmap_id = match.group(1)

    try:
        # Fetch from osu! API and persist essential fields
        bm = api.beatmap(beatmap_id)
        if not bm:
            messages.error(request, f"Beatmap '{beatmap_id}' not found.")
            return redirect('home')

        beatmap, _ = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)

        # Basic fields
        # Set IDs and set metadata used by card links
        beatmap.beatmapset_id = getattr(bm._beatmapset, 'id', beatmap.beatmapset_id)
        beatmap.title = getattr(bm._beatmapset, 'title', beatmap.title)
        beatmap.artist = getattr(bm._beatmapset, 'artist', beatmap.artist)

        # Preserve original set owner, but compute display creator
        if not beatmap.original_creator:
            beatmap.original_creator = getattr(bm._beatmapset, 'creator', None)
        beatmap.creator = join_diff_creators(bm)
        # Default listed_owner/id to set owner if not set
        if not beatmap.listed_owner:
            owner_name = getattr(bm._beatmapset, 'creator', None) or beatmap.creator
            owner_id = getattr(bm._beatmapset, 'user_id', None)
            beatmap.listed_owner = owner_name
            try:
                beatmap.listed_owner_id = str(owner_id or '')
            except Exception:
                pass

        beatmap.cover_image_url = getattr(getattr(bm._beatmapset, 'covers', None), 'cover_2x', None)
        beatmap.version = getattr(bm, 'version', beatmap.version)
        beatmap.total_length = getattr(bm, 'total_length', beatmap.total_length)
        beatmap.bpm = getattr(bm, 'bpm', beatmap.bpm)
        beatmap.cs = getattr(bm, 'cs', beatmap.cs)
        beatmap.drain = getattr(bm, 'drain', beatmap.drain)
        beatmap.accuracy = getattr(bm, 'accuracy', beatmap.accuracy)
        beatmap.ar = getattr(bm, 'ar', beatmap.ar)
        beatmap.difficulty_rating = getattr(bm, 'difficulty_rating', beatmap.difficulty_rating)

        status_mapping = {
            -2: 'Graveyard',
            -1: 'WIP',
            0: 'Pending',
            1: 'Ranked',
            2: 'Approved',
            3: 'Qualified',
            4: 'Loved',
        }
        status_val = getattr(getattr(bm, 'status', None), 'value', None)
        beatmap.status = status_mapping.get(status_val, getattr(beatmap, 'status', 'Unknown'))
        beatmap.playcount = getattr(bm, 'playcount', beatmap.playcount)
        beatmap.favourite_count = getattr(getattr(bm, '_beatmapset', None), 'favourite_count', getattr(beatmap, 'favourite_count', 0))

        api_mode_value = getattr(bm, 'mode', beatmap.mode)
        beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode_value), 'unknown')
        # Save per-difficulty last updated timestamp
        try:
            beatmap.last_updated = getattr(bm, 'last_updated', beatmap.last_updated)
        except Exception:
            pass

        beatmap.save()

        # Warm caches for PP and timeseries so the detail page has data immediately
        try:
            get_or_compute_pp(beatmap)
            get_or_compute_modded_pps(beatmap)
        except Exception:
            pass
        try:
            get_or_compute_timeseries(beatmap, window_seconds=1, mods=None)
        except Exception:
            pass

        # Update genres
        try:
            genres = fetch_genres(beatmap.artist, beatmap.title)
            if genres:
                beatmap.genres.set(get_or_create_genres(genres))
            else:
                beatmap.genres.clear()
        except Exception:
            # Non-fatal
            pass

        return redirect('beatmap_detail', beatmap_id=beatmap_id)

    except Exception as exc:
        messages.error(request, f'Error adding beatmap: {exc}')
        return redirect('home')
