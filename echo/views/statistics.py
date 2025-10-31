# echo/views/statistics.py

from __future__ import annotations

# Standard library
from typing import Iterable, List, Tuple
import re
import math
from urllib.parse import urlencode
import json

# Third-party
from ossapi.enums import ScoreType, GameMode, UserBeatmapType, UserLookupKey

# Django
from django.db.models import Q, Count, F, Value, IntegerField, Subquery, OuterRef, Exists, Max
from django.db.models.functions import Coalesce
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string

# Local
from ..models import Beatmap, Tag, TagApplication, SavedSearch
from .auth import api
from .shared import format_length_hms
from ..helpers.rosu_utils import get_or_compute_pp


def _resolve_osu_user(user_query: str) -> Tuple[int | None, str | None, str | None]:
    """Return (user_id, username, error_message). Accepts id or username."""
    if not user_query:
        return None, None, None
    try:
        if user_query.isdigit():
            u = api.user(int(user_query), key=UserLookupKey.ID)
        else:
            u = api.user(user_query, key=UserLookupKey.USERNAME)
        return int(u.id), str(u.username), None
    except Exception as exc:
        return None, None, f"Could not resolve user '{user_query}': {exc}"


def _compute_weighted_queryset(qs, include_tags: Iterable[str], exact_tags: Iterable[str], predicted_mode: str = 'include'):
    """Annotate queryset with tag_weight using the same logic as search.

    This mirrors the in-view helper used by the search endpoint.
    """
    include_tags = list(include_tags or [])
    exact_tags = list(exact_tags or [])

    # Filter by include_tags using through model, and honor predicted toggle
    if include_tags:
        if predicted_mode == 'include':
            qs = qs.filter(tagapplication__tag__name__in=include_tags).distinct()
        elif predicted_mode == 'exclude':
            qs = qs.filter(
                tagapplication__tag__name__in=include_tags,
                tagapplication__user__isnull=False,
            ).distinct()
        elif predicted_mode == 'only':
            qs = (
                qs.filter(
                    tagapplication__tag__name__in=include_tags,
                    tagapplication__user__isnull=True,
                )
                .exclude(
                    id__in=TagApplication.objects.filter(user__isnull=False).values('beatmap_id')
                )
                .distinct()
            )

    # Count total tags per map; when excluding predictions, count only user-applied
    if predicted_mode == 'include':
        total_sub = (
            Beatmap.objects.filter(pk=OuterRef('pk'))
            .annotate(real_count=Count('tags'))
            .values('real_count')[:1]
        )
    else:  # exclude and only: count only user-applied for denominator
        total_sub = (
            Beatmap.objects.filter(pk=OuterRef('pk'))
            .annotate(real_count=Count('tagapplication', filter=Q(tagapplication__user__isnull=False)))
            .values('real_count')[:1]
        )

    # Weight factor for predicted tags (scaled down) when included/only
    p_w = Value(0.5 if predicted_mode in ['include', 'only'] else 0.0)

    qs = (
        qs.annotate(
            # User vs predicted counts
            u_tag_match_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=include_tags) & Q(tagapplication__user__isnull=False)),
                distinct=True,
            ),
            p_tag_match_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=include_tags) & Q(tagapplication__user__isnull=True)),
                distinct=True,
            ),
            u_exact_total_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=exact_tags) & Q(tagapplication__user__isnull=False)),
            ),
            p_exact_total_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=exact_tags) & Q(tagapplication__user__isnull=True)),
            ),
            u_exact_distinct_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=exact_tags) & Q(tagapplication__user__isnull=False)),
                distinct=True,
            ),
            p_exact_distinct_count=Count(
                'tagapplication__tag',
                filter=(Q(tagapplication__tag__name__in=exact_tags) & Q(tagapplication__user__isnull=True)),
                distinct=True,
            ),
            total_tag_count=Subquery(total_sub),
        )
        .annotate(
            matched_distinct_total=(
                (F('u_tag_match_count') + F('p_tag_match_count')) if predicted_mode in ['include', 'only'] else F('u_tag_match_count')
            ),
            weighted_exact_distinct=F('u_exact_distinct_count') + F('p_exact_distinct_count') * p_w,
            weighted_exact_total=F('u_exact_total_count') + F('p_exact_total_count') * p_w,
            weighted_tag_match=F('u_tag_match_count') + F('p_tag_match_count') * p_w,
        )
        .annotate(
            tag_miss_match_count=Value(len(include_tags), output_field=IntegerField()) - F('matched_distinct_total'),
            tag_surplus_count=F('total_tag_count') - F('matched_distinct_total'),
            tag_weight=(
                (F('weighted_exact_distinct') * Value(5.0) +
                 F('weighted_exact_total')   * Value(1.0) +
                 F('weighted_tag_match')     * Value(0.1)) /
                (F('tag_miss_match_count')   * Value(1.0) + (F('tag_surplus_count') * Value(3.0)))
            ),
        )
    )
    return qs


def _attach_display_extras(beatmaps: Iterable[Beatmap]):
    for bm in beatmaps:
        try:
            bm.pp = get_or_compute_pp(bm)
        except Exception:
            bm.pp = None
        bm.length_formatted = format_length_hms(getattr(bm, 'total_length', None))
    return beatmaps


def _compute_player_stats(osu_id: int | None, source: str):
    """Compute player tag distribution and most related map for given source.

    Returns (labels, counts, most_related_beatmap_or_None)
    """
    if not osu_id:
        return [], [], None

    beatmaps_for_player = Beatmap.objects.none()
    try:
        if source == 'top':
            scores = api.user_scores(osu_id, ScoreType.BEST, mode=GameMode.OSU, limit=100)
            ids = [str(getattr(s.beatmap, 'id', '')) for s in scores if getattr(s, 'beatmap', None)]
            ids = [i for i in ids if i]
            if ids:
                beatmaps_for_player = Beatmap.objects.filter(beatmap_id__in=ids)
        else:  # 'fav'
            fav_sets = api.user_beatmaps(osu_id, UserBeatmapType.FAVOURITE, limit=100)
            set_ids = [str(getattr(bs, 'id', '')) for bs in fav_sets]
            set_ids = [i for i in set_ids if i]
            if set_ids:
                beatmaps_for_player = Beatmap.objects.filter(beatmapset_id__in=set_ids)
    except Exception:
        beatmaps_for_player = Beatmap.objects.none()

    if not beatmaps_for_player.exists():
        return [], [], None

    rows = (
        TagApplication.objects
        .filter(beatmap__in=beatmaps_for_player, true_negative=False)
        .values('tag__name')
        .annotate(c=Count('id'))
        .order_by('-c')[:15]
    )
    player_labels = [r['tag__name'] for r in rows if r['tag__name']]
    player_counts = [int(r['c']) for r in rows]

    include_tags = player_labels
    exact_tags = include_tags
    most_related = None
    if include_tags:
        # Start with all beatmaps annotated by tag weight
        annotated_all = _compute_weighted_queryset(Beatmap.objects.all(), include_tags, exact_tags, predicted_mode='include')

        # Compute median star rating from the player's maps to guide similarity
        stars = list(beatmaps_for_player.values_list('difficulty_rating', flat=True))
        stars = [s for s in stars if s is not None]
        if stars:
            stars_sorted = sorted(stars)
            n = len(stars_sorted)
            median_star = stars_sorted[n//2] if n % 2 == 1 else (stars_sorted[n//2 - 1] + stars_sorted[n//2]) / 2.0
            # Apply a reasonable star window around the median (±10% of median, min width 0.5)
            delta = max(0.5, float(median_star) * 0.10)
            star_min = max(0.0, float(median_star) - delta)
            star_max = min(15.0, float(median_star) + delta)
            annotated_all = annotated_all.filter(difficulty_rating__gte=star_min, difficulty_rating__lte=star_max)

        most_related = annotated_all.order_by('-tag_weight').first()
        _attach_display_extras([m for m in [most_related] if m])
    return player_labels, player_counts, most_related


def statistics(request: HttpRequest):
    """Statistics page with Mapper and Player sections.

    Accepts GET params:
      - user: osu! id or username
      - source: 'top' (top 100 plays) or 'fav' (favourites)
    """
    user_query = (request.GET.get('user') or '').strip()
    source = (request.GET.get('source') or 'top').strip().lower()
    if source not in ['top', 'fav']:
        source = 'top'

    osu_id, username, resolve_error = _resolve_osu_user(user_query)

    # Defaults when no user resolved yet
    mapper_labels: List[str] = []
    mapper_counts: List[int] = []
    mapper_click_queries: List[str] = []
    mapper_most: Beatmap | None = None
    mapper_least: Beatmap | None = None

    player_labels: List[str] = []
    player_counts: List[int] = []
    most_related: Beatmap | None = None

    # -------------------- My Statistics (current user) --------------------
    my_total_applications: int = 0
    my_maps_tagged_count: int = 0
    my_avg_tags_per_map: float | int = 0
    my_tag_usage = []
    my_consensus_rate: float | int = 0
    my_star_hist_labels: List[str] = []
    my_star_hist_counts: List[int] = []
    my_top_mappers = []
    my_activity_beatmaps: List[Beatmap] = []
    my_activity_page: int = 1
    my_activity_total_pages: int = 1
    my_search_history = []
    my_saved_searches = []

    try:
        if getattr(request, 'user', None) and request.user.is_authenticated:
            user_apps = TagApplication.objects.filter(user=request.user, true_negative=False)
            my_total_applications = user_apps.count()
            my_maps_tagged_count = user_apps.values('beatmap_id').distinct().count()
            my_avg_tags_per_map = (float(my_total_applications) / my_maps_tagged_count) if my_maps_tagged_count else 0.0
            my_tag_usage = list(
                user_apps.values('tag__name').annotate(c=Count('id')).order_by('-c', 'tag__name')
            )

            # Consensus rate: share of your tag applications that others also applied on same map
            other_exists = TagApplication.objects.filter(
                beatmap_id=OuterRef('beatmap_id'), tag_id=OuterRef('tag_id'), true_negative=False
            ).exclude(user=request.user)
            with_consensus = user_apps.annotate(has_other=Exists(other_exists)).filter(has_other=True).count()
            my_consensus_rate = ((with_consensus / float(my_total_applications)) * 100.0) if my_total_applications else 0.0

            # Star histogram (0.25 bins) over distinct maps you've tagged
            # Cap at 15.0 and group anything >= 14.75 into the last ("14.75+") bin
            stars = list(
                Beatmap.objects.filter(tagapplication__user=request.user, tagapplication__true_negative=False)
                .distinct()
                .values_list('difficulty_rating', flat=True)
            )
            stars = [float(s) for s in stars if s is not None]
            if stars:
                bin_w = 0.25
                upper_cap = 15.0
                last_bin_start = upper_cap - bin_w  # 14.75
                # Use observed minimum to keep chart compact
                s_min = min(stars)
                start_val = bin_w * math.floor(max(0.0, s_min) / bin_w)
                # Number of bins from start_val up to and including [14.75, 15.0]
                num_bins = int(round((last_bin_start - start_val) / bin_w)) + 1
                if num_bins < 1:
                    # If all data are >= 14.75, show a single aggregated bin
                    num_bins = 1
                    start_val = last_bin_start
                bins = [0] * num_bins
                for s in stars:
                    if s >= last_bin_start:
                        idx = num_bins - 1
                    else:
                        idx = int(math.floor((s - start_val) / bin_w))
                        if idx < 0:
                            idx = 0
                        if idx >= num_bins:
                            idx = num_bins - 1
                    bins[idx] += 1
                labels = [f"{(start_val + i * bin_w):.2f}" for i in range(num_bins)]
                # Replace final label with 14.75+
                labels[-1] = f"{last_bin_start:.2f}+"
                my_star_hist_counts = bins
                my_star_hist_labels = labels

            # Most-tagged mappers (by distinct maps you've tagged)
            mapper_rows = (
                user_apps
                .values('beatmap__listed_owner')
                .annotate(map_count=Count('beatmap_id', distinct=True))
                .exclude(beatmap__listed_owner__isnull=True)
                .exclude(beatmap__listed_owner='')
                .order_by('-map_count', 'beatmap__listed_owner')[:10]
            )
            my_top_mappers = [{'listed_owner': r['beatmap__listed_owner'], 'count': int(r['map_count'])} for r in mapper_rows]

            # My Tagging Activity: last maps you tagged (distinct beatmaps ordered by newest tag)
            try:
                page_size = 10
                my_activity_page = max(1, int((request.GET.get('my_page') or '1').strip()))
            except Exception:
                page_size = 10
                my_activity_page = 1
            activity_qs = (
                TagApplication.objects
                .filter(user=request.user, true_negative=False)
                .values('beatmap_id')
                .annotate(last_ts=Max('created_at'))
                .order_by('-last_ts')
            )
            total_groups = activity_qs.count()
            my_activity_total_pages = max(1, int(math.ceil(total_groups / float(page_size))))
            offset = (my_activity_page - 1) * page_size
            ids = list(activity_qs.values_list('beatmap_id', flat=True)[offset:offset + page_size])
            bm_by_id = {bm.id: bm for bm in Beatmap.objects.filter(id__in=ids)}
            my_activity_beatmaps = [bm_by_id[i] for i in ids if i in bm_by_id]
            # Light-weight display extras only (avoid PP compute for responsiveness)
            for bm in my_activity_beatmaps:
                try:
                    bm.length_formatted = format_length_hms(getattr(bm, 'total_length', None))
                except Exception:
                    bm.length_formatted = None

            # My Search History (from session) + Saved searches from DB
            history = request.session.get('search_history', [])
            # Build a quick lookup of saved signatures
            saved_qs = SavedSearch.objects.filter(user=request.user).order_by('-updated_at')
            saved_set = set()
            for s in saved_qs:
                saved_set.add((s.query or '', s.params_json or ''))
            # Build linkable items for recent history (first 10)
            def _qs(p):
                try:
                    return urlencode(p or {}, doseq=True)
                except Exception:
                    return ''
            my_search_history = []
            for h in (history[:15] if isinstance(history, list) else []):
                q = h.get('query') or ''
                p_json = json.dumps(h.get('params') or {}, sort_keys=True)
                my_search_history.append({
                    'id': h.get('id'),
                    'query': q,
                    'saved': (q, p_json) in saved_set,
                    'qs': _qs(h.get('params') or {}),
                    'ts': int(h.get('ts') or 0),
                })
            # Saved list for display
            my_saved_searches = [
                {
                    'id': s.id,
                    'title': s.title,
                    'query': s.query or '',
                    'qs': s.params_json and urlencode(json.loads(s.params_json), doseq=True) or '',
                }
                for s in saved_qs
            ]
    except Exception:
        # Leave defaults if any error
        pass

    if username:
        # -------------------- Mapper Statistics --------------------
        # Only consider maps where this user is the listed owner (by id).
        # Support CSV ids when multiple owners are present.
        user_maps = Beatmap.objects.filter(listed_owner_id__regex=r'(^|,)\s*%s(\s*,|$)' % re.escape(str(osu_id)))

        mapper_tag_rows = (
            TagApplication.objects
            .filter(beatmap__in=user_maps, true_negative=False)
            .values('tag__name')
            .annotate(c=Count('beatmap', distinct=True))  # count each tag once per map
            .order_by('-c')[:15]
        )
        mapper_labels = [r['tag__name'] for r in mapper_tag_rows if r['tag__name']]
        mapper_counts = [int(r['c']) for r in mapper_tag_rows]

        # Click-through queries: "{listed_owner}" .{tag}
        def _enc(n: str) -> str:
            return f'"{n}"' if ' ' in n else n
        listed_owner_name = (user_maps.values_list('listed_owner', flat=True).first() or username)
        mapper_click_queries = [f"{_enc(listed_owner_name)} .{_enc(t)}" for t in mapper_labels]

        # Most/least representative among this mapper's maps
        include_tags = mapper_labels
        exact_tags = include_tags
        if include_tags:
            annotated = _compute_weighted_queryset(user_maps, include_tags, exact_tags, predicted_mode='include')
            # Most representative: highest tag_weight
            mapper_most = annotated.order_by('-tag_weight').first()
            # Least representative: lowest tag_weight
            mapper_least = annotated.order_by('tag_weight').first()

        # Attach PP/length and tags_with_counts for mapper cards
        for bm in [mapper_most, mapper_least]:
            if bm:
                _attach_display_extras([bm])
                try:
                    from .search import annotate_search_results_with_tags
                    annotate_search_results_with_tags(Beatmap.objects.filter(id__in=[bm.id]), request.user, include_predicted_toggle=True)
                except Exception:
                    pass

        # -------------------- Player Statistics --------------------
        player_labels, player_counts, most_related = _compute_player_stats(osu_id, source)

    # Latest maps (default tab): newest entries by DB insert order
    # Skip maps with no tags (predicted or user-applied) and avoid heavy PP computation here
    latest_maps = list(
        Beatmap.objects
        .filter(tagapplication__true_negative=False)
        .order_by('-id')
        .distinct()[:10]
        .prefetch_related('genres')
    )

    # Render template
    return render(
        request,
        'statistics.html',
        {
            'input_user': user_query,
            'resolved_user_id': osu_id,
            'resolved_username': username,
            'resolve_error': resolve_error,
            'source': source,
            # Mapper section
            'mapper_labels': mapper_labels,
            'mapper_counts': mapper_counts,
            'mapper_click_queries': mapper_click_queries,
            'mapper_most_map': mapper_most,
            'mapper_least_map': mapper_least,
            # Player section
            'player_labels': player_labels,
            'player_counts': player_counts,
            'most_related_map': most_related,
            # My stats
            'my_total_applications': my_total_applications,
            'my_maps_tagged_count': my_maps_tagged_count,
            'my_avg_tags_per_map': my_avg_tags_per_map,
            'my_tag_usage': my_tag_usage,
            'my_consensus_rate': my_consensus_rate,
            'my_star_hist_labels': my_star_hist_labels,
            'my_star_hist_counts': my_star_hist_counts,
            'my_top_mappers': my_top_mappers,
            'my_activity_beatmaps': my_activity_beatmaps,
            'my_activity_page': my_activity_page,
            'my_activity_total_pages': my_activity_total_pages,
            'my_search_history': my_search_history,
            'my_saved_searches': my_saved_searches,
            # Latest maps tab
            'latest_maps': latest_maps,
        },
    )


def statistics_player_data(request: HttpRequest):
    """AJAX endpoint to refresh Player Statistics when source toggles."""
    user_query = (request.GET.get('user') or '').strip()
    source = (request.GET.get('source') or 'top').strip().lower()
    if source not in ['top', 'fav']:
        source = 'top'

    osu_id, username, err = _resolve_osu_user(user_query)
    labels, counts, most_related = _compute_player_stats(osu_id, source)

    html = ''
    if most_related:
        try:
            # Attach tags for the most_related card as well
            try:
                from .search import annotate_search_results_with_tags
                annotate_search_results_with_tags(Beatmap.objects.filter(id__in=[most_related.id]), request.user, include_predicted_toggle=True)
            except Exception:
                pass
            html = render_to_string('partials/tag_card.html', {'beatmap': most_related}, request=request)
        except Exception:
            html = ''

    return JsonResponse({
        'labels': labels,
        'counts': counts,
        'most_related_html': html or '<p>No data.</p>',
        'resolved_username': username,
        'error': err,
    })


