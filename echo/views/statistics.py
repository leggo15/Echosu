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
from django.db.models.functions import Coalesce, TruncHour, TruncDate
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone

# Local
from ..models import Beatmap, Tag, TagApplication, SavedSearch
from ..models import AnalyticsSearchEvent, AnalyticsClickEvent
from collections import Counter
from .auth import api
from .shared import format_length_hms
from ..helpers.rosu_utils import get_or_compute_pp


def _tokenize_query_terms(raw_query: str) -> set[str]:
    terms: set[str] = set()
    if not raw_query:
        return terms
    pattern = r'[-.]?"[^"]+"|[-.]?[^"\s]+'
    for match in re.findall(pattern, raw_query):
        token = match.strip()
        if not token:
            continue
        if token[0] in '.-':
            token = token[1:]
        token = token.strip('"').strip("'").strip()
        if token:
            terms.add(token.lower())
    return terms


def _query_contains_phrase(raw_query: str, phrase_lower: str) -> bool:
    if not (raw_query and phrase_lower):
        return False
    raw = raw_query.lower()
    pattern = r'(^|[\s,.;:\-])' + re.escape(phrase_lower) + r'($|[\s,.;:\-])'
    return re.search(pattern, raw) is not None


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

    # -------------------- Global Statistics (all users/maps) --------------------
    global_total_applications: int = 0
    global_maps_tagged_count: int = 0
    global_avg_tags_per_map: float | int = 0
    global_predicted_applications: int = 0
    global_predicted_only_maps_count: int = 0
    global_star_hist_labels: List[str] = []
    global_star_hist_counts: List[int] = []
    global_human_star_counts: List[int] = []
    global_pred_star_counts: List[int] = []
    global_top_mappers = []

    try:
        # Totals
        ta_pos = TagApplication.objects.filter(true_negative=False)
        global_total_applications = ta_pos.count()
        global_maps_tagged_count = ta_pos.values('beatmap_id').distinct().count()
        global_avg_tags_per_map = (float(global_total_applications) / global_maps_tagged_count) if global_maps_tagged_count else 0.0
        global_predicted_applications = ta_pos.filter(user__isnull=True).count()

        # Predicted-only maps
        pred_only_ids = (
            Beatmap.objects
            .annotate(user_pos=Count('tagapplication', filter=Q(tagapplication__true_negative=False, tagapplication__user__isnull=False)))
            .annotate(pred_pos=Count('tagapplication', filter=Q(tagapplication__true_negative=False, tagapplication__user__isnull=True)))
            .filter(user_pos=0, pred_pos__gt=0)
            .values_list('id', flat=True)
        )
        global_predicted_only_maps_count = len(list(pred_only_ids))

        # Helper: bin list of stars into 0.25 width with final 14.75+
        def bin_stars(stars_list: List[float]) -> tuple[list[str], list[int]]:
            stars_list = [float(s) for s in stars_list if s is not None]
            if not stars_list:
                return [], []
            bin_w = 0.25
            upper_cap = 15.0
            last_bin_start = upper_cap - bin_w  # 14.75
            s_min = min(stars_list)
            start_val = bin_w * math.floor(max(0.0, s_min) / bin_w)
            # Bins up to and including 14.75, plus an overflow bin for 15.00+
            num_base = int(round((last_bin_start - start_val) / bin_w)) + 1
            if num_base < 1:
                num_base = 1
                start_val = last_bin_start
            bins = [0] * (num_base + 1)  # extra overflow at the end
            for s in stars_list:
                if s >= upper_cap:
                    idx = num_base  # overflow bin (15.00+)
                else:
                    idx = int(math.floor((s - start_val) / bin_w))
                    if idx < 0:
                        idx = 0
                    if idx >= num_base:
                        idx = num_base - 1
                bins[idx] += 1
            labels = [f"{(start_val + i * bin_w):.2f}" for i in range(num_base)]
            labels.append(f"{upper_cap:.2f}+")
            return labels, bins

        # Global star distribution over ALL maps in DB (not only tagged)
        all_stars = list(Beatmap.objects.values_list('difficulty_rating', flat=True))
        global_star_hist_labels, global_star_hist_counts = bin_stars([float(s) for s in all_stars if s is not None])

        # Human vs Predicted distributions
        human_ids = list(
            TagApplication.objects
            .filter(true_negative=False, user__isnull=False)
            .values_list('beatmap_id', flat=True)
            .distinct()
        )
        pred_only_ids_list = list(pred_only_ids)
        human_stars = list(Beatmap.objects.filter(id__in=human_ids).values_list('difficulty_rating', flat=True))
        pred_only_stars = list(Beatmap.objects.filter(id__in=pred_only_ids_list).values_list('difficulty_rating', flat=True))

        # Align bins between human and predicted using global labels as base if available
        # If global labels not available, compute from human set
        if global_star_hist_labels:
            # Build mapping for index by start value (strip '+' for last)
            def build_bins_with_labels(stars_list: List[float], labels: List[str]) -> List[int]:
                bin_w = 0.25
                # Extract start values
                starts: List[float] = []
                for i, lb in enumerate(labels):
                    if lb.endswith('+'):
                        starts.append(float(lb[:-1]))
                    else:
                        starts.append(float(lb))
                counts = [0] * len(labels)
                last_start = starts[-1]
                for s in stars_list:
                    if s is None:
                        continue
                    s = float(s)
                    if s >= last_start:
                        idx = len(labels) - 1
                    else:
                        idx = int(math.floor((s - starts[0]) / bin_w))
                        if idx < 0:
                            idx = 0
                        if idx >= len(labels):
                            idx = len(labels) - 1
                    counts[idx] += 1
                return counts

            global_human_star_counts = build_bins_with_labels([float(s) for s in human_stars if s is not None], global_star_hist_labels)
            global_pred_star_counts = build_bins_with_labels([float(s) for s in pred_only_stars if s is not None], global_star_hist_labels)
        else:
            # Fallback to independent binning
            _, global_human_star_counts = bin_stars([float(s) for s in human_stars if s is not None])
            _, global_pred_star_counts = bin_stars([float(s) for s in pred_only_stars if s is not None])

        # Top mappers by distinct maps with human-applied tags
        top_rows = (
            TagApplication.objects
            .filter(true_negative=False, user__isnull=False)
            .values('beatmap__listed_owner')
            .annotate(map_count=Count('beatmap_id', distinct=True))
            .exclude(beatmap__listed_owner__isnull=True)
            .exclude(beatmap__listed_owner='')
            .order_by('-map_count', 'beatmap__listed_owner')[:25]
        )
        global_top_mappers = [{'listed_owner': r['beatmap__listed_owner'], 'count': int(r['map_count'])} for r in top_rows]
    except Exception:
        pass

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
            # Important: count DISTINCT BEATMAPS, not distinct star values.
            # First get distinct beatmap ids you've tagged, then fetch their stars.
            id_list = list(
                TagApplication.objects
                .filter(user=request.user, true_negative=False)
                .values_list('beatmap_id', flat=True)
                .distinct()
            )
            stars = list(
                Beatmap.objects
                .filter(id__in=id_list)
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
                num_base = int(round((last_bin_start - start_val) / bin_w)) + 1
                if num_base < 1:
                    # If all data are >= 14.75, show that base bin plus overflow
                    num_base = 1
                    start_val = last_bin_start
                bins = [0] * (num_base + 1)  # extra overflow bin for 15.00+
                for s in stars:
                    if s >= upper_cap:
                        idx = num_base  # overflow
                    else:
                        idx = int(math.floor((s - start_val) / bin_w))
                        if idx < 0:
                            idx = 0
                        if idx >= num_base:
                            idx = num_base - 1
                    bins[idx] += 1
                labels = [f"{(start_val + i * bin_w):.2f}" for i in range(num_base)]
                labels.append(f"{upper_cap:.2f}+")
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
            # Pre-annotate with tags so server-side fallback in tag_card can render immediately
            bm_qs = Beatmap.objects.filter(id__in=ids)
            try:
                from .search import annotate_search_results_with_tags
                annotate_search_results_with_tags(bm_qs, request.user, include_predicted_toggle=True)
            except Exception:
                pass
            bm_by_id = {bm.id: bm for bm in bm_qs}
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
        ids_to_annotate = [bm.id for bm in [mapper_most, mapper_least] if bm]
        for bm in [mapper_most, mapper_least]:
            if bm:
                _attach_display_extras([bm])
        if ids_to_annotate:
            try:
                from .search import annotate_search_results_with_tags
                annotated_qs = annotate_search_results_with_tags(Beatmap.objects.filter(id__in=ids_to_annotate), request.user, include_predicted_toggle=True)
                id_to_bm = {b.id: b for b in annotated_qs}
                if mapper_most and mapper_most.id in id_to_bm:
                    try: mapper_most.tags_with_counts = id_to_bm[mapper_most.id].tags_with_counts
                    except Exception: pass
                if mapper_least and mapper_least.id in id_to_bm:
                    try: mapper_least.tags_with_counts = id_to_bm[mapper_least.id].tags_with_counts
                    except Exception: pass
            except Exception:
                pass

        # -------------------- Player Statistics --------------------
        player_labels, player_counts, most_related = _compute_player_stats(osu_id, source)
        # Attach tags for initial render of Most Related card (AJAX updates will handle later)
        if most_related:
            try:
                from .search import annotate_search_results_with_tags
                annotated_qs = annotate_search_results_with_tags(Beatmap.objects.filter(id__in=[most_related.id]), request.user, include_predicted_toggle=True)
                for b in annotated_qs:
                    if b.id == most_related.id:
                        try: most_related.tags_with_counts = b.tags_with_counts
                        except Exception: pass
                        break
            except Exception:
                pass

    # Latest maps (default tab): newest entries by DB insert order
    # Skip maps with no tags (predicted or user-applied) and avoid heavy PP computation here
    latest_maps = (
        Beatmap.objects
        .filter(tagapplication__true_negative=False)
        .prefetch_related('genres')
        .order_by('-id')
        .distinct()[:10]
    )
    try:
        from .search import annotate_search_results_with_tags
        annotate_search_results_with_tags(latest_maps, request.user, include_predicted_toggle=True)
    except Exception:
        pass

    # Render template
    return render(
        request,
        'statistics.html',
        {
            # Global
            'global_total_applications': global_total_applications,
            'global_maps_tagged_count': global_maps_tagged_count,
            'global_avg_tags_per_map': global_avg_tags_per_map,
            'global_predicted_applications': global_predicted_applications,
            'global_predicted_only_maps_count': global_predicted_only_maps_count,
            'global_star_hist_labels': global_star_hist_labels,
            'global_star_hist_counts': global_star_hist_counts,
            'global_human_star_counts': global_human_star_counts,
            'global_pred_star_counts': global_pred_star_counts,
            'global_top_mappers': global_top_mappers,
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


def statistics_latest_maps(request: HttpRequest):
    """AJAX endpoint: return the 10 latest maps (with any positive tags) as HTML cards."""
    try:
        latest_maps = (
            Beatmap.objects
            .filter(tagapplication__true_negative=False)
            .prefetch_related('genres')
            .order_by('-id')
            .distinct()[:10]
        )
        try:
            from .search import annotate_search_results_with_tags
            annotate_search_results_with_tags(latest_maps, request.user, include_predicted_toggle=True)
        except Exception:
            pass
        html_parts: list[str] = []
        for bm in latest_maps:
            try:
                html_parts.append(render_to_string('partials/tag_card.html', {'beatmap': bm}, request=request))
            except Exception:
                continue
        return JsonResponse({ 'html': ''.join(html_parts) })
    except Exception:
        return JsonResponse({ 'html': '' })


def statistics_latest_searches(request: HttpRequest):
    """AJAX endpoint: return the latest 15 search events as HTML (staff only)."""
    try:
        if not getattr(request.user, 'is_staff', False):
            return JsonResponse({ 'html': '' }, status=403)
        events = (
            AnalyticsSearchEvent.objects
            .exclude(query__isnull=True)
            .exclude(query__exact='')
            .order_by('-created_at')[:15]
        )
        html = render_to_string('partials/admin_search_log.html', {'events': events}, request=request)
        return JsonResponse({ 'html': html })
    except Exception:
        return JsonResponse({ 'html': '' })


def statistics_latest_events(request: HttpRequest):
    """AJAX: return merged search + button logs (paged, default 30)."""
    try:
        if not getattr(request.user, 'is_staff', False):
            return JsonResponse({ 'html': '' }, status=403)

        try:
            offset = max(0, int((request.GET.get('offset') or '0').strip()))
        except Exception:
            offset = 0
        try:
            limit = max(1, min(100, int((request.GET.get('limit') or '30').strip())))
        except Exception:
            limit = 30

        # Fetch more than we need from each source so combined ordering is stable.
        # (Merged streams require oversampling; 2x is usually enough for low-volume admin analytics.)
        fetch_n = max(60, (offset + limit) * 2)

        search_events = []
        for e in (
            AnalyticsSearchEvent.objects
            .exclude(query__isnull=True)
            .exclude(query__exact='')
            .order_by('-created_at')[:fetch_n]
        ):
            results = e.results_count
            if results is None:
                try:
                    flags = e.flags or {}
                    results = flags.get('results_count')
                except Exception:
                    results = None
            flags = e.flags if isinstance(e.flags, dict) else {}
            mode_norm = Tag.normalize_mode(flags.get('mode'))
            star_min = flags.get('star_min')
            star_max = flags.get('star_max')
            star_range = None
            try:
                if star_min is not None or star_max is not None:
                    sm = str(star_min) if star_min is not None else '?'
                    sx = str(star_max) if star_max is not None else '?'
                    star_range = f'⭐ {sm}–{sx}'
            except Exception:
                star_range = None

            # Build "Open" URL (best-effort; old events may not have flags)
            href = None
            try:
                params = {}
                params['query'] = e.query or ''
                # Only include mode when non-std
                if mode_norm and mode_norm != Tag.MODE_STD:
                    params['mode'] = mode_norm
                if star_min is not None:
                    params['star_min'] = str(star_min)
                if star_max is not None:
                    params['star_max'] = str(star_max)
                if e.sort:
                    params['sort'] = e.sort
                if e.predicted_mode:
                    params['include_predicted'] = e.predicted_mode
                # Status flags
                if flags.get('status_ranked'):
                    params['status_ranked'] = 'ranked'
                if flags.get('status_loved'):
                    params['status_loved'] = 'loved'
                if flags.get('status_unranked'):
                    params['status_unranked'] = 'unranked'
                ex = flags.get('exclude_player')
                if ex:
                    params['exclude_player'] = str(ex)
                keys = flags.get('keys')
                if keys:
                    params['keys'] = str(keys)
                href = '/search_results/?' + urlencode(params)
            except Exception:
                href = None
            search_events.append({
                'type': 'search',
                'client_id': e.client_id or 'anonymous',
                'created_at': e.created_at,
                'label': (e.query or '(no query)')[:80],
                'results': results if results is not None else '?',
                'star_range': star_range,
                'mode': mode_norm,
                'href': href,
            })

        click_events = [
            {
                'type': 'click',
                'client_id': e.client_id or 'anonymous',
                'created_at': e.created_at,
                'label': e.action or 'click',
                'meta': e.meta or {},
            }
            for e in AnalyticsClickEvent.objects.order_by('-created_at')[:fetch_n]
        ]

        combined = search_events + click_events
        combined.sort(key=lambda ev: ev['created_at'], reverse=True)
        window = combined[offset:offset + limit]
        has_more = len(combined) > (offset + limit)

        palette = ['#ff9f43', '#1e90ff', '#2ecc71', '#e74c3c', '#9b59b6', '#f1c40f', '#e67e22', '#16a085']
        color_map = {}
        palette_index = 0
        for ev in window:
            cid = ev['client_id']
            if cid not in color_map:
                color_map[cid] = palette[palette_index % len(palette)]
                palette_index += 1
            ev['color'] = color_map[cid]
            ev['text_color'] = color_map[cid] + 'cc'

        html = render_to_string('partials/admin_event_log.html', {'events': window}, request=request)
        return JsonResponse({ 'html': html, 'has_more': bool(has_more) })
    except Exception:
        return JsonResponse({ 'html': '' })


def _hour_floor(dt):
    return dt.replace(minute=0, second=0, microsecond=0, tzinfo=dt.tzinfo)


def _day_floor(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=dt.tzinfo)


def _week_floor(dt):
    """Floor datetime to start of week (Monday 00:00) in the same timezone."""
    try:
        days = int(dt.weekday())  # Monday=0..Sunday=6
    except Exception:
        days = 0
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=dt.tzinfo) - timezone.timedelta(days=days)


def _safe_client_id(v) -> str | None:
    try:
        s = (v or '').strip()
        return s or None
    except Exception:
        return None


def _compute_followup_ids_for_searches(search_rows: list[dict], action_names: list[str]) -> set[str]:
    """Return set of search_event_id strings that have at least one followup click with matching client_id."""
    try:
        if not search_rows:
            return set()
        event_id_to_client: dict[str, str] = {}
        event_ids = []
        for r in search_rows:
            eid = r.get('event_id')
            cid = _safe_client_id(r.get('client_id'))
            if not eid or not cid:
                continue
            eid_str = str(eid)
            event_id_to_client[eid_str] = cid
            event_ids.append(eid)
        if not event_ids:
            return set()
        click_qs = (
            AnalyticsClickEvent.objects
            .filter(action__in=action_names, search_event_id__in=event_ids)
            .values('search_event_id', 'client_id')
            .distinct()
        )
        matched: set[str] = set()
        for c in click_qs:
            sid = c.get('search_event_id')
            cid = _safe_client_id(c.get('client_id'))
            if not sid or not cid:
                continue
            sid_str = str(sid)
            if event_id_to_client.get(sid_str) == cid:
                matched.add(sid_str)
        return matched
    except Exception:
        return set()


def _bucket_series(
    search_rows: list[dict],
    start,
    bucket_seconds: int,
    bucket_count: int,
    followup_ids: set[str],
) -> tuple[list[int], list[int], list[float]]:
    """Return (search_counts, followup_counts, followup_pct) per bucket."""
    counts = [0] * bucket_count
    f_counts = [0] * bucket_count
    for r in (search_rows or []):
        try:
            created = r.get('created_at')
            if not created:
                continue
            idx = int((created - start).total_seconds() // bucket_seconds)
            if idx < 0 or idx >= bucket_count:
                continue
            counts[idx] += 1
            eid = r.get('event_id')
            if eid and str(eid) in followup_ids:
                f_counts[idx] += 1
        except Exception:
            continue
    pct: list[float] = []
    for i in range(bucket_count):
        pct.append((float(f_counts[i]) / float(counts[i]) * 100.0) if counts[i] else 0.0)
    return counts, f_counts, pct


def statistics_admin_data(request: HttpRequest):
    """AJAX endpoint returning admin analytics (staff only)."""
    if not getattr(request.user, 'is_staff', False):
        return JsonResponse({}, status=403)
    try:
        now = timezone.now()
        # Follow-up actions that represent a "download / take-away" from a search.
        # Must include view_on_osu to match the existing tag stat "% with Direct/View (all time)".
        download_actions = ['direct', 'view_on_osu', 'beatconnect', 'bulk_direct_all']

        # -------------------- Overall Search -> Download conversion (all time) --------------------
        total_searches_all = (
            AnalyticsSearchEvent.objects
            .exclude(query__isnull=True)
            .exclude(query__exact='')
            .count()
        )
        downloads_all = 0
        pct_downloads_all = 0.0
        try:
            click_rows = list(
                AnalyticsClickEvent.objects
                .filter(action__in=download_actions)
                .exclude(search_event_id__isnull=True)
                .values('search_event_id', 'client_id')
                .distinct()
            )
            referenced_ids = [c.get('search_event_id') for c in click_rows if c.get('search_event_id')]
            referenced_ids = [i for i in referenced_ids if i]
            if referenced_ids:
                # Only load searches that were referenced by a download click (fast-path).
                search_map = {
                    str(eid): _safe_client_id(cid)
                    for eid, cid in (
                        AnalyticsSearchEvent.objects
                        .filter(event_id__in=referenced_ids)
                        .exclude(query__isnull=True)
                        .exclude(query__exact='')
                        .values_list('event_id', 'client_id')
                    )
                    if _safe_client_id(cid)
                }
                matched: set[str] = set()
                for c in click_rows:
                    sid = c.get('search_event_id')
                    cid = _safe_client_id(c.get('client_id'))
                    if not sid or not cid:
                        continue
                    sid_str = str(sid)
                    if search_map.get(sid_str) == cid:
                        matched.add(sid_str)
                downloads_all = len(matched)
        except Exception:
            downloads_all = 0
        pct_downloads_all = (float(downloads_all) / float(total_searches_all) * 100.0) if total_searches_all else 0.0

        # Hourly (last 24 hours)
        hour_labels: list[str] = []
        hour_search_counts: list[int] = []
        hour_unique_counts: list[int] = []
        for i in range(24):
            start = _hour_floor(now - timezone.timedelta(hours=(23 - i)))
            end = start + timezone.timedelta(hours=1)
            hour_labels.append(start.strftime('%H:%M'))
            # Searches
            try:
                c = (
                    AnalyticsSearchEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .exclude(query__isnull=True)
                    .exclude(query__exact='')
                    .count()
                )
            except Exception:
                c = 0
            hour_search_counts.append(int(c))
            # Unique users across search + click
            try:
                s_ids = set(
                    AnalyticsSearchEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .values_list('client_id', flat=True)
                    .distinct()
                )
                c_ids = set(
                    AnalyticsClickEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .values_list('client_id', flat=True)
                    .distinct()
                )
                uniq = len({i for i in (s_ids | c_ids) if i})
            except Exception:
                uniq = 0
            hour_unique_counts.append(int(uniq))

        # Download % per hour (last 24h)
        hour_dl_followups: list[int] = [0] * 24
        hour_dl_pct: list[float] = [0.0] * 24
        try:
            start_24h = _hour_floor(now - timezone.timedelta(hours=23))
            end_24h = start_24h + timezone.timedelta(hours=24)
            hour_search_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_24h, created_at__lt=end_24h)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at')
            )
            hour_followup_ids = _compute_followup_ids_for_searches(hour_search_rows, download_actions)
            _, f_counts, pct = _bucket_series(hour_search_rows, start_24h, 3600, 24, hour_followup_ids)
            hour_dl_followups = [int(v) for v in f_counts]
            hour_dl_pct = [float(v) for v in pct]
        except Exception:
            pass

        # Daily (last 30 days)
        day_labels: list[str] = []
        day_search_counts: list[int] = []
        day_unique_counts: list[int] = []
        for i in range(30):
            start = _day_floor(now - timezone.timedelta(days=(29 - i)))
            end = start + timezone.timedelta(days=1)
            day_labels.append(start.strftime('%Y-%m-%d'))
            try:
                c = (
                    AnalyticsSearchEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .exclude(query__isnull=True)
                    .exclude(query__exact='')
                    .count()
                )
            except Exception:
                c = 0
            day_search_counts.append(int(c))
            try:
                s_ids = set(
                    AnalyticsSearchEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .values_list('client_id', flat=True)
                    .distinct()
                )
                c_ids = set(
                    AnalyticsClickEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .values_list('client_id', flat=True)
                    .distinct()
                )
                uniq = len({i for i in (s_ids | c_ids) if i})
            except Exception:
                uniq = 0
            day_unique_counts.append(int(uniq))

        # Download % per day (last 30d)
        day_dl_followups: list[int] = [0] * 30
        day_dl_pct: list[float] = [0.0] * 30
        try:
            start_30d = _day_floor(now - timezone.timedelta(days=29))
            end_30d = start_30d + timezone.timedelta(days=30)
            day_search_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_30d, created_at__lt=end_30d)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at')
            )
            day_followup_ids = _compute_followup_ids_for_searches(day_search_rows, download_actions)
            _, f_counts_d, pct_d = _bucket_series(day_search_rows, start_30d, 24 * 3600, 30, day_followup_ids)
            day_dl_followups = [int(v) for v in f_counts_d]
            day_dl_pct = [float(v) for v in pct_d]
        except Exception:
            pass

        # Weekly (last 52 weeks) - used for "Year" view (52 candles)
        week_labels: list[str] = []
        week_search_counts: list[int] = []
        week_unique_counts: list[int] = []
        week_dl_followups: list[int] = [0] * 52
        week_dl_pct: list[float] = [0.0] * 52
        start_52w = _week_floor(now) - timezone.timedelta(weeks=51)
        end_52w = start_52w + timezone.timedelta(weeks=52)
        try:
            week_search_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_52w, created_at__lt=end_52w)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at')
            )
            week_followup_ids = _compute_followup_ids_for_searches(week_search_rows, download_actions)
            w_counts, w_f, w_pct = _bucket_series(week_search_rows, start_52w, 7 * 24 * 3600, 52, week_followup_ids)
            week_dl_followups = [int(v) for v in w_f]
            week_dl_pct = [float(v) for v in w_pct]

            # Unique users per week: union of search + click client_id in that week bucket
            week_click_rows = list(
                AnalyticsClickEvent.objects
                .filter(created_at__gte=start_52w, created_at__lt=end_52w)
                .values('client_id', 'created_at')
            )
            week_client_sets = [set() for _ in range(52)]
            for r in week_search_rows:
                try:
                    idx = int((r['created_at'] - start_52w).total_seconds() // (7 * 24 * 3600))
                    if 0 <= idx < 52:
                        cid = _safe_client_id(r.get('client_id'))
                        if cid:
                            week_client_sets[idx].add(cid)
                except Exception:
                    continue
            for r in week_click_rows:
                try:
                    idx = int((r['created_at'] - start_52w).total_seconds() // (7 * 24 * 3600))
                    if 0 <= idx < 52:
                        cid = _safe_client_id(r.get('client_id'))
                        if cid:
                            week_client_sets[idx].add(cid)
                except Exception:
                    continue

            for i in range(52):
                wk_start = start_52w + timezone.timedelta(weeks=i)
                week_labels.append(wk_start.strftime('%Y-%m-%d'))
                week_search_counts.append(int(w_counts[i]))
                week_unique_counts.append(int(len(week_client_sets[i])))
        except Exception:
            week_labels = [(start_52w + timezone.timedelta(weeks=i)).strftime('%Y-%m-%d') for i in range(52)]
            week_search_counts = [0] * 52
            week_unique_counts = [0] * 52

        # All-time (up to 52 buckets)
        all_labels: list[str] = []
        all_search_counts: list[int] = []
        all_unique_counts: list[int] = []
        all_dl_followups: list[int] = []
        all_dl_pct: list[float] = []
        try:
            first_ts = AnalyticsSearchEvent.objects.order_by('created_at').values_list('created_at', flat=True).first()
        except Exception:
            first_ts = None
        if first_ts:
            all_start = _day_floor(first_ts)
            span_sec = max(1, int((now - all_start).total_seconds()))
            bucket_sec = int(math.ceil(span_sec / 52.0))
            bucket_count = int(math.ceil(span_sec / float(bucket_sec)))
            bucket_count = min(52, max(1, bucket_count))
            all_end = all_start + timezone.timedelta(seconds=bucket_sec * bucket_count)
            try:
                all_search_rows = list(
                    AnalyticsSearchEvent.objects
                    .filter(created_at__gte=all_start, created_at__lt=all_end)
                    .exclude(query__isnull=True)
                    .exclude(query__exact='')
                    .values('event_id', 'client_id', 'created_at')
                )
                all_followup_ids = _compute_followup_ids_for_searches(all_search_rows, download_actions)
                a_counts, a_f, a_pct = _bucket_series(all_search_rows, all_start, bucket_sec, bucket_count, all_followup_ids)
                all_dl_followups = [int(v) for v in a_f]
                all_dl_pct = [float(v) for v in a_pct]

                all_click_rows = list(
                    AnalyticsClickEvent.objects
                    .filter(created_at__gte=all_start, created_at__lt=all_end)
                    .values('client_id', 'created_at')
                )
                all_client_sets = [set() for _ in range(bucket_count)]
                for r in all_search_rows:
                    try:
                        idx = int((r['created_at'] - all_start).total_seconds() // bucket_sec)
                        if 0 <= idx < bucket_count:
                            cid = _safe_client_id(r.get('client_id'))
                            if cid:
                                all_client_sets[idx].add(cid)
                    except Exception:
                        continue
                for r in all_click_rows:
                    try:
                        idx = int((r['created_at'] - all_start).total_seconds() // bucket_sec)
                        if 0 <= idx < bucket_count:
                            cid = _safe_client_id(r.get('client_id'))
                            if cid:
                                all_client_sets[idx].add(cid)
                    except Exception:
                        continue
                for i in range(bucket_count):
                    bstart = all_start + timezone.timedelta(seconds=bucket_sec * i)
                    all_labels.append(bstart.strftime('%Y-%m-%d'))
                    all_search_counts.append(int(a_counts[i]))
                    all_unique_counts.append(int(len(all_client_sets[i])))
            except Exception:
                all_labels, all_search_counts, all_unique_counts, all_dl_followups, all_dl_pct = [], [], [], [], []

        # Average clicks per action per day (last 30 days)
        clicks_since = _day_floor(now) - timezone.timedelta(days=29)
        rows = (
            AnalyticsClickEvent.objects
            .filter(created_at__gte=clicks_since)
            .values('action')
            .annotate(c=Count('id'))
        )
        avg_clicks = {}
        click_counts_30d = {}
        for r in rows:
            a = r.get('action') or ''
            cnt = int(r.get('c') or 0)
            avg_clicks[a] = float(cnt) / 30.0
            click_counts_30d[a] = cnt

        # Last used timestamp per action (all time)
        click_last_rows = (
            AnalyticsClickEvent.objects
            .values('action')
            .annotate(last_ts=Max('created_at'))
        )
        last_used_per_action = {}
        for r in click_last_rows:
            a = r.get('action') or ''
            ts = r.get('last_ts')
            if not a or not ts:
                continue
            try:
                last_used_per_action[a] = ts.isoformat()
            except Exception:
                continue

        # Top 25 searched tags (last 90 days for performance)
        tags_since = now - timezone.timedelta(days=90)
        tag_counter: Counter[str] = Counter()
        valid_tags = {
            ((tag_name or '').strip().lower(), mode or Tag.MODE_STD): (tag_name, mode)
            for tag_name, mode in Tag.objects.values_list('name', 'mode')
        }
        try:
            qs_tags = (
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=tags_since)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('tags', 'query', 'flags')
            )
            for event in qs_tags:
                raw_query = event.get('query') or ''
                flags = event.get('flags') or {}
                search_mode = Tag.normalize_mode(flags.get('mode')) if isinstance(flags, dict) else Tag.MODE_STD
                tokens = _tokenize_query_terms(raw_query)
                tags = event.get('tags') or []
                seen = set()
                for t in tags:
                    tag_lower = (str(t or '').strip().lower())
                    key = (tag_lower, search_mode)
                    canonical_tuple = valid_tags.get(key)
                    if not canonical_tuple or tag_lower in seen:
                        continue
                    if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                        continue
                    display_name, mode = canonical_tuple
                    tag_counter[(display_name, mode)] += 1
                    seen.add(tag_lower)
        except Exception:
            tag_counter = Counter()
        top_tags = [
            {'name': name, 'mode': mode, 'count': int(cnt)}
            for (name, mode), cnt in tag_counter.most_common(25)
        ]

        return JsonResponse({
            'searches': {
                'hour': { 'labels': hour_labels, 'counts': hour_search_counts, 'dl_followups': hour_dl_followups, 'dl_pct': hour_dl_pct },
                'day': { 'labels': day_labels, 'counts': day_search_counts, 'dl_followups': day_dl_followups, 'dl_pct': day_dl_pct },
                'year': { 'labels': week_labels, 'counts': week_search_counts, 'dl_followups': week_dl_followups, 'dl_pct': week_dl_pct },
                'all': { 'labels': all_labels, 'counts': all_search_counts, 'dl_followups': all_dl_followups, 'dl_pct': all_dl_pct },
            },
            'uniques': {
                'hour': { 'labels': hour_labels, 'counts': hour_unique_counts },
                'day': { 'labels': day_labels, 'counts': day_unique_counts },
                'year': { 'labels': week_labels, 'counts': week_unique_counts },
                'all': { 'labels': all_labels, 'counts': all_unique_counts },
            },
            'download_conversion': {
                'label': 'Search→Direct/View conversion (all time)',
                'searches_all_time': total_searches_all,
                'searches_with_download_all_time': downloads_all,
                'percent_with_download_all_time': pct_downloads_all,
            },
            'avg_clicks_per_action_per_day': avg_clicks,
            'click_counts_30d': click_counts_30d,
            'last_used_per_action': last_used_per_action,
            'top_tags': top_tags,
        })
    except Exception:
        return JsonResponse({})


def statistics_admin_tag(request: HttpRequest):
    """AJAX endpoint: per-tag usage and click-through stats (staff only)."""
    if not getattr(request.user, 'is_staff', False):
        return JsonResponse({}, status=403)
    tag_raw = (request.GET.get('tag') or '').strip()
    requested_mode = Tag.normalize_mode(request.GET.get('mode'))
    if not tag_raw:
        return JsonResponse({'tag': '', 'searches': {}, 'totals': {}, 'click_through': {}})
    tag_obj = Tag.objects.filter(name__iexact=tag_raw, mode=requested_mode).first()
    if not tag_obj:
        tag_obj = Tag.objects.filter(name__iexact=tag_raw).first()
        if tag_obj:
            requested_mode = tag_obj.mode
    if not tag_obj:
        return JsonResponse({'tag': '', 'searches': {}, 'totals': {}, 'click_through': {}})
    tag_name = tag_obj.name
    tag_lower = tag_name.lower()
    try:
        now = timezone.now()
        download_actions = ['direct', 'view_on_osu', 'beatconnect', 'bulk_direct_all']
        # Define 24h and 30d windows
        start_24h = _hour_floor(now - timezone.timedelta(hours=23))
        start_30d = _day_floor(now - timezone.timedelta(days=29))
        start_52w = _week_floor(now) - timezone.timedelta(weeks=51)

        # Prepare bins
        hour_labels: list[str] = []
        for i in range(24):
            h = _hour_floor(start_24h + timezone.timedelta(hours=i))
            hour_labels.append(h.strftime('%H:%M'))
        hour_counts = [0] * 24

        day_labels: list[str] = []
        for i in range(30):
            d = _day_floor(start_30d + timezone.timedelta(days=i))
            day_labels.append(d.strftime('%Y-%m-%d'))
        day_counts = [0] * 30

        year_labels: list[str] = [(start_52w + timezone.timedelta(weeks=i)).strftime('%Y-%m-%d') for i in range(52)]
        year_counts = [0] * 52

        hour_dl_pct = [0.0] * 24
        day_dl_pct = [0.0] * 30
        year_dl_pct = [0.0] * 52

        # Fetch events for last 24h and 30d in one go
        events_30d = list(
            AnalyticsSearchEvent.objects
            .filter(created_at__gte=start_30d)
            .exclude(query__isnull=True)
            .exclude(query__exact='')
            .values('event_id', 'client_id', 'created_at', 'query', 'flags')
        )

        total_30d_searches = 0
        unique_30d_clients: set[str] = set()

        for e in events_30d:
            flags = e.get('flags') or {}
            search_mode = Tag.normalize_mode(flags.get('mode'))
            if search_mode != requested_mode:
                continue
            raw_query = e.get('query') or ''
            tokens = _tokenize_query_terms(raw_query)
            if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                continue
            created = e.get('created_at') or now
            # 30d daily bucket
            delta_days = int((created - start_30d).total_seconds() // (24 * 3600))
            if 0 <= delta_days < 30:
                day_counts[delta_days] += 1
                total_30d_searches += 1
                cid = e.get('client_id') or None
                if cid:
                    unique_30d_clients.add(str(cid))
            # 24h hourly bucket (subset)
            if created >= start_24h:
                delta_hours = int((created - start_24h).total_seconds() // 3600)
                if 0 <= delta_hours < 24:
                    hour_counts[delta_hours] += 1

            # 52w weekly bucket (subset)
            if created >= start_52w:
                delta_weeks = int((created - start_52w).total_seconds() // (7 * 24 * 3600))
                if 0 <= delta_weeks < 52:
                    year_counts[delta_weeks] += 1

        # Download % per bucket (hour/day/year) for this tag
        try:
            # Hour
            hour_end = start_24h + timezone.timedelta(hours=24)
            hour_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_24h, created_at__lt=hour_end)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at', 'query', 'flags')
            )
            filtered_hour = []
            for r in hour_rows:
                flags = r.get('flags') or {}
                search_mode = Tag.normalize_mode(flags.get('mode'))
                if search_mode != requested_mode:
                    continue
                raw_query = r.get('query') or ''
                tokens = _tokenize_query_terms(raw_query)
                if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                    continue
                filtered_hour.append(r)
            hour_followup_ids = _compute_followup_ids_for_searches(filtered_hour, download_actions)
            _, _, hpct = _bucket_series(filtered_hour, start_24h, 3600, 24, hour_followup_ids)
            hour_dl_pct = [float(v) for v in hpct]
        except Exception:
            pass
        try:
            # Day
            day_end = start_30d + timezone.timedelta(days=30)
            day_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_30d, created_at__lt=day_end)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at', 'query', 'flags')
            )
            filtered_day = []
            for r in day_rows:
                flags = r.get('flags') or {}
                search_mode = Tag.normalize_mode(flags.get('mode'))
                if search_mode != requested_mode:
                    continue
                raw_query = r.get('query') or ''
                tokens = _tokenize_query_terms(raw_query)
                if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                    continue
                filtered_day.append(r)
            day_followup_ids = _compute_followup_ids_for_searches(filtered_day, download_actions)
            _, _, dpct = _bucket_series(filtered_day, start_30d, 24 * 3600, 30, day_followup_ids)
            day_dl_pct = [float(v) for v in dpct]
        except Exception:
            pass
        try:
            # Year (52 weeks)
            year_end = start_52w + timezone.timedelta(weeks=52)
            year_rows = list(
                AnalyticsSearchEvent.objects
                .filter(created_at__gte=start_52w, created_at__lt=year_end)
                .exclude(query__isnull=True)
                .exclude(query__exact='')
                .values('event_id', 'client_id', 'created_at', 'query', 'flags')
            )
            filtered_year = []
            for r in year_rows:
                flags = r.get('flags') or {}
                search_mode = Tag.normalize_mode(flags.get('mode'))
                if search_mode != requested_mode:
                    continue
                raw_query = r.get('query') or ''
                tokens = _tokenize_query_terms(raw_query)
                if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                    continue
                filtered_year.append(r)
            year_followup_ids = _compute_followup_ids_for_searches(filtered_year, download_actions)
            y_counts, _, ypct = _bucket_series(filtered_year, start_52w, 7 * 24 * 3600, 52, year_followup_ids)
            year_counts = [int(v) for v in y_counts]
            year_dl_pct = [float(v) for v in ypct]
        except Exception:
            pass

        # All-time totals and click-through (direct/view_on_osu)
        all_events = list(
            AnalyticsSearchEvent.objects
            .exclude(query__isnull=True)
            .exclude(query__exact='')
            .values('event_id', 'client_id', 'query', 'flags')
        )
        event_id_to_client: dict[str, str] = {}
        tag_event_ids: set[str] = set()
        unique_all_clients: set[str] = set()
        for e in all_events:
            flags = e.get('flags') or {}
            search_mode = Tag.normalize_mode(flags.get('mode'))
            if search_mode != requested_mode:
                continue
            raw_query = e.get('query') or ''
            tokens = _tokenize_query_terms(raw_query)
            if (tag_lower not in tokens) and (not _query_contains_phrase(raw_query, tag_lower)):
                continue
            eid = str(e.get('event_id'))
            cid = e.get('client_id') or None
            tag_event_ids.add(eid)
            if cid:
                cid_str = str(cid)
                unique_all_clients.add(cid_str)
                event_id_to_client[eid] = cid_str

        total_all_searches = len(tag_event_ids)

        # Click-through: same client direct or view_on_osu
        clicks_with_followup: set[str] = set()
        if tag_event_ids:
            click_qs = AnalyticsClickEvent.objects.filter(
                action__in=['direct', 'view_on_osu'],
                search_event_id__in=list(tag_event_ids),
            ).values('search_event_id', 'client_id')
            for c in click_qs:
                sid = c.get('search_event_id') or ''
                cid = c.get('client_id') or None
                if not sid or not cid:
                    continue
                sid_str = str(sid)
                cid_str = str(cid)
                if event_id_to_client.get(sid_str) == cid_str:
                    clicks_with_followup.add(sid_str)

        num_followup = len(clicks_with_followup)
        pct_followup = float(num_followup) / float(total_all_searches) * 100.0 if total_all_searches else 0.0

        avg_searches_per_day_30d = float(total_30d_searches) / 30.0
        avg_unique_per_day_30d = float(len(unique_30d_clients)) / 30.0

        return JsonResponse({
            'tag': tag_name,
            'mode': requested_mode,
            'searches': {
                'hour': { 'labels': hour_labels, 'counts': hour_counts, 'dl_pct': hour_dl_pct },
                'day': { 'labels': day_labels, 'counts': day_counts, 'dl_pct': day_dl_pct },
                'year': { 'labels': year_labels, 'counts': year_counts, 'dl_pct': year_dl_pct },
            },
            'totals': {
                'searches_all_time': total_all_searches,
                'searches_last_30d': total_30d_searches,
                'avg_searches_per_day_30d': avg_searches_per_day_30d,
                'unique_users_all_time': len(unique_all_clients),
                'unique_users_last_30d': len(unique_30d_clients),
                'avg_unique_users_per_day_30d': avg_unique_per_day_30d,
            },
            'click_through': {
                'searches_with_direct_or_view_all_time': num_followup,
                'percent_with_direct_or_view_all_time': pct_followup,
            },
        })
    except Exception:
        return JsonResponse({})


