# echosu/views/search.py
'''
Beatmap search view and helpers.

This pass groups imports, removes duplicates, and switches remaining
string literals to single quotes wherever practical. No runtime logic
was altered.
'''

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import re
import time
import shlex
from collections import defaultdict

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
from nltk.stem import PorterStemmer
from ossapi.enums import ScoreType, GameMode, UserBeatmapType

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib.auth.models import User  # noqa: F401  (used indirectly)
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.db.models import (
    Q,
    Count,
    F,
    Value,
    IntegerField,
    Subquery,
    OuterRef,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, Tag, TagApplication, UserProfile
from .auth import api
from .shared import (
    compute_attribute_windows,
    derive_filters_from_tags,
    build_similar_maps_query,
)
from ..operators import (
    handle_quotes,
    handle_exclusion,
    handle_inclusion,
    handle_attribute_queries,
    handle_general_inclusion,
)
from ..utils import QueryContext
## NOTE: PP computation is intentionally not invoked in the search view to avoid
## heavy per-result work on every request. If PP is required, precompute it
## offline and store on model fields, or compute asynchronously.

# ----------------------------- Search Views ----------------------------- #

def search_results(request):
    '''Main search endpoint returning paginated beatmap results.''' 

    # -------------------------------------------------------------
    # Helper functions scoped inside the view (left unchanged).
    # -------------------------------------------------------------
    stemmer = PorterStemmer()

    def stem_word(word: str) -> str:
        return stemmer.stem(word.lower())

    def stem_phrase(phrase: str) -> str:
        return ' '.join(stem_word(w) for w in phrase.split())

    def parse_query_with_quotes(raw_query: str):
        '''Split query, treating quoted substrings as single tokens.''' 
        lexer = shlex.shlex(raw_query, posix=True)
        lexer.whitespace_split = True
        lexer.quotes = '"\''
        tokens = []
        try:
            for token in lexer:
                is_quoted = ' ' in token
                tokens.append((token, is_quoted))
        except ValueError:
            fixed_query = raw_query.replace('"', '').replace("'", '')
            lexer = shlex.shlex(fixed_query, posix=True)
            lexer.whitespace_split = True
            lexer.quotes = ''
            for token in lexer:
                tokens.append((token, False))
        return tokens

    def process_search_terms(parsed_terms):
        stemmed = set()
        for term, _ in parsed_terms:
            sanitized = term.strip('"\'')
            stemmed.add(stem_phrase(sanitized) if ' ' in sanitized else stem_word(sanitized))
        return stemmed

    def identify_exact_match_tags(include_tags, stemmed_terms):
        exact = set()
        for tag in include_tags:
            sanitized = tag.strip('"\'')
            st_tag = stem_phrase(sanitized) if ' ' in sanitized else stem_word(sanitized)
            if st_tag in stemmed_terms:
                exact.add(tag)
                continue
            for word in sanitized.split():
                if stem_word(word) in stemmed_terms:
                    exact.add(tag)
                    break
        return exact

    def annotate_and_order_beatmaps(qs, include_tags, exact_tags, sort, predicted_mode):
        # Filter by include_tags using through model, and honor predicted toggle
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
            total_tag_count_expr = Count('tags', distinct=True)
        else:  # exclude and only: count only user-applied applications for denominator
                        total_tag_count_expr = Count('tagapplication__tag', filter=Q(tagapplication__user__isnull=False), distinct=True)
        if sort == 'tag_weight':
            # Weight factor for predicted tags (0.5 when included/only, else 0)
            p_w = Value(0.5 if predicted_mode in ['include', 'only'] else 0.0)

            # Build subqueries that are independent of the include_tags filter join
            base_ta_sq = TagApplication.objects.filter(beatmap_id=OuterRef('id'))
            if predicted_mode == 'exclude':
                base_ta_sq = base_ta_sq.filter(user__isnull=False)
            elif predicted_mode == 'only':
                base_ta_sq = base_ta_sq.filter(user__isnull=True)

            total_app_subq = (
                base_ta_sq
                .values('beatmap_id')
                .annotate(cnt=Count('id'))
                .values('cnt')[:1]
            )
            matched_app_subq = (
                base_ta_sq
                .filter(tag__name__in=include_tags)
                .values('beatmap_id')
                .annotate(cnt=Count('id'))
                .values('cnt')[:1]
            )
            # Distinct tag names present on map (and matched) irrespective of join filters
            distinct_tag_total_subq = (
                base_ta_sq
                .values('beatmap_id')
                .annotate(cnt=Count('tag_id', distinct=True))
                .values('cnt')[:1]
            )
            matched_distinct_subq = (
                base_ta_sq
                .filter(tag__name__in=include_tags)
                .values('beatmap_id')
                .annotate(cnt=Count('tag_id', distinct=True))
                .values('cnt')[:1]
            )

            qs = (
                qs.annotate(
                    # Per-beatmap total and matched tag application counts (non-distinct)
                    total_app_count=Coalesce(Subquery(total_app_subq), Value(0)),
                    matched_app_count=Coalesce(Subquery(matched_app_subq), Value(0)),
                    # Per-beatmap distinct tag name counts
                    total_distinct_count=Coalesce(Subquery(distinct_tag_total_subq), Value(0)),
                    matched_distinct_count=Coalesce(Subquery(matched_distinct_subq), Value(0)),
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
                    total_tag_count=total_tag_count_expr,
                )
                .annotate(
                    # Unweighted total matched distinct tags (for denominator)
                    matched_distinct_total=(
                        (F('u_tag_match_count') + F('p_tag_match_count')) if predicted_mode in ['include', 'only'] else F('u_tag_match_count')
                    ),
                    # Weighted components: predicted scaled down by p_w
                    weighted_exact_distinct=F('u_exact_distinct_count') + F('p_exact_distinct_count') * p_w,
                    weighted_exact_total=F('u_exact_total_count') + F('p_exact_total_count') * p_w,
                    weighted_tag_match=F('u_tag_match_count') + F('p_tag_match_count') * p_w,
                )
                .annotate(
                    # 1) Missing distinct search tags not present on map
                    tag_miss_match_count=Value(len(include_tags), output_field=IntegerField()) - F('matched_distinct_count'),
                    # 2) Distinct extra tag names on map that are not in the search
                    tag_surplus_count_distinct=F('total_distinct_count') - F('matched_distinct_count'),
                    # 3) Extra duplicate applications beyond the first of tags not in the search
                    tag_surplus_count=(F('total_app_count') - F('matched_app_count')) - F('tag_surplus_count_distinct'),
                    tag_weight=(
                        (F('weighted_exact_distinct') * Value(5.0) +
                         F('weighted_exact_total') * Value(1.0) +
                         F('weighted_tag_match') * Value(0.1)) /
                        (
                            (F('tag_miss_match_count') * Value(3)) +
                            (F('tag_surplus_count_distinct') * Value(5)) +
                            (F('tag_surplus_count') * Value(10))
                        )
                    ),
                )
                .order_by('-tag_weight')
            )
            
        else:
            # When sorting by popularity, compute a numeric popularity score so it can be displayed
            qs = qs.annotate(
                popularity=F('favourite_count') * Value(0.02) + F('playcount') * Value(0.0001)
            ).order_by('-popularity')
        return qs

    # -------------------------------------------------------------
    # Query parameter handling begins here.
    # -------------------------------------------------------------
    query = request.GET.get('query', '').strip()

    # Normalize commas in query input:
    # - If any quotes are present, just remove commas (treat existing quoted phrases as-is)
    # - If no quotes present but commas exist, split on commas and quote each token
    if ',' in query:
        if '"' in query or "'" in query:
            # Remove commas, keep spacing readable
            query = re.sub(r'\s*,\s*', ' ', query)
        else:
            parts = [p.strip() for p in query.split(',') if p.strip()]
            query = ' '.join(f'"{p}"' for p in parts)
    selected_mode = request.GET.get('mode', 'osu').strip().lower()
    star_min = request.GET.get('star_min', '0').strip()
    star_max = request.GET.get('star_max', '10').strip()
    sort = request.GET.get('sort', '')
    exclude_player = (request.GET.get('exclude_player') or 'none').strip().lower()
    fetch_exclude_now = (request.GET.get('fetch_exclude_now') or '1').strip()
    # Predicted mode: 'include' (default), 'exclude', 'only'
    raw_pred = (request.GET.get('include_predicted') or '').strip().lower()
    if raw_pred in ['exclude', '0', 'false', 'off']:
        predicted_mode = 'exclude'
    elif raw_pred in ['only']:
        predicted_mode = 'only'
    else:
        predicted_mode = 'include'

    status_ranked = request.GET.get('status_ranked', False)
    status_loved = request.GET.get('status_loved', False)
    status_unranked = request.GET.get('status_unranked', False)

    try:
        star_min = max(float(star_min), 0)
    except ValueError:
        star_min = 0.0
    try:
        star_max = float(star_max)
        if star_max < star_min:
            star_max = 10.0
    except ValueError:
        star_max = 10.0

    MODE_MAPPING = {'osu': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
    GAME_MODE_ENUM = {
        'osu': GameMode.OSU,
        'taiko': GameMode.TAIKO,
        'catch': GameMode.CATCH,
        'mania': GameMode.MANIA,
    }
    mapped_mode = MODE_MAPPING.get(selected_mode, 'osu')

    beatmaps = Beatmap.objects.filter(mode__iexact=mapped_mode)
    beatmaps = beatmaps.filter(difficulty_rating__gte=star_min)
    if star_max < 15:
        beatmaps = beatmaps.filter(difficulty_rating__lte=star_max)

    # Exclude user's Top plays or Favourites if requested
    if exclude_player in ['top', 'fav']:
        try:
            osu_id = request.session.get('osu_id')
            if not osu_id and request.user.is_authenticated:
                osu_id = (
                    UserProfile.objects
                    .filter(user=request.user)
                    .values_list('osu_id', flat=True)
                    .first()
                )
            if osu_id:
                if exclude_player == 'top':
                    try:
                        # Cache by mode to avoid repeated fetches during pagination/sorting
                        cache_key = f'exclude_top_ids_{selected_mode}'
                        cache_ts_key = f'{cache_key}_ts'
                        ids = request.session.get(cache_key) or []
                        ts = request.session.get(cache_ts_key) or 0
                        now = int(time.time())
                        if fetch_exclude_now == '1' and (not ids or (now - int(ts)) > 600):
                            gm = GAME_MODE_ENUM.get(selected_mode, GameMode.OSU)
                            scores = api.user_scores(int(osu_id), ScoreType.BEST, mode=gm, limit=100)
                            ids = [str(getattr(s.beatmap, 'id', '')) for s in scores if getattr(s, 'beatmap', None)]
                            ids = [i for i in ids if i]
                            request.session[cache_key] = ids
                            request.session[cache_ts_key] = now
                        if ids:
                            beatmaps = beatmaps.exclude(beatmap_id__in=ids)
                    except Exception:
                        pass
                elif exclude_player == 'fav':
                    try:
                        cache_key = 'exclude_fav_set_ids'
                        cache_ts_key = f'{cache_key}_ts'
                        set_ids = request.session.get(cache_key) or []
                        ts = request.session.get(cache_ts_key) or 0
                        now = int(time.time())
                        if fetch_exclude_now == '1' and (now - int(ts)) > 600 or (fetch_exclude_now == '1' and not set_ids):
                            fav_sets = api.user_beatmaps(int(osu_id), UserBeatmapType.FAVOURITE, limit=100)
                            set_ids = [str(getattr(bs, 'id', '')) for bs in fav_sets]
                            set_ids = [i for i in set_ids if i]
                            request.session[cache_key] = set_ids
                            request.session[cache_ts_key] = now
                        if set_ids:
                            beatmaps = beatmaps.exclude(beatmapset_id__in=set_ids)
                    except Exception:
                        pass
        except Exception:
            pass

    if any([status_ranked, status_loved, status_unranked]):
        status_q = Q()
        if status_ranked:
            status_q |= Q(status='Ranked') | Q(status='Approved')
        if status_loved:
            status_q |= Q(status='Loved')
        if status_unranked:
            status_q |= Q(status__in=['Graveyard', 'WIP', 'Pending', 'Qualified'])
        beatmaps = beatmaps.filter(status_q)

    parsed_terms = parse_query_with_quotes(query)
    beatmaps, include_tags = build_query_conditions(beatmaps, [t[0] for t in parsed_terms], predicted_mode)

    stemmed_terms = process_search_terms(parsed_terms)
    exact_tags = identify_exact_match_tags(include_tags, stemmed_terms)

    if sort not in ['tag_weight', 'popularity']:
        # Default depends on query presence: tag_weight when query present, else popularity
        sort = 'tag_weight' if include_tags else 'popularity'

    if include_tags:
        beatmaps = annotate_and_order_beatmaps(beatmaps, include_tags, exact_tags, sort, predicted_mode)
    else:
        # When no include tags are specified, still respect the predicted toggle:
        # - include: show all
        # - exclude: only maps with user-applied tags
        # - only: only maps that have predicted tags (and optionally no user tags if that is desired later)
        if predicted_mode == 'exclude':
            beatmaps = beatmaps.filter(tagapplication__user__isnull=False).distinct()
        elif predicted_mode == 'only':
            beatmaps = (
                beatmaps.filter(tagapplication__user__isnull=True)
                .exclude(id__in=TagApplication.objects.filter(user__isnull=False).values('beatmap_id'))
                .distinct()
            )

        beatmaps = beatmaps.annotate(
            total_tag_apply_count=Count('tagapplication'),
            tag_weight=F('total_tag_apply_count'),
            popularity=F('favourite_count') * 0.02 + F('playcount') * 0.0001,
        )
        beatmaps = beatmaps.order_by('-' + sort) if sort in ['tag_weight', 'popularity'] else beatmaps.order_by('-favourite_count', '-playcount')

    # Save toggle into request so downstream helpers can read it via thread locals
    # Expose predicted_mode via context only

    # Lightweight queryset hints to avoid unnecessary payloads/N+1s
    beatmaps = beatmaps.defer('rosu_timeseries').prefetch_related('genres')

    # Server-side paginate to a modest page size to reduce template rendering cost
    paginator = Paginator(beatmaps, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    annotate_search_results_with_tags(page_obj.object_list, request.user, predicted_mode in ['include', 'only'])

    # Attach derived, lightweight display fields only
    for bm in page_obj.object_list:
        try:
            # Import lazily to avoid circular on module import
            from .shared import format_length_hms  # type: ignore
            bm.length_formatted = format_length_hms(bm.total_length)
        except Exception:
            bm.length_formatted = None

    return render(
        request,
        'search_results.html',
        {
            'beatmaps': page_obj,
            'query': query,
            'star_min': star_min,
            'star_max': star_max,
            'sort': sort,
            'status_ranked': status_ranked,
            'status_loved': status_loved,
            'status_unranked': status_unranked,
            'include_predicted': predicted_mode,
        },
    )

# ---------------------------------------------------------------------------
# Helper utilities (mostly unchanged, but quote style unified)
# ---------------------------------------------------------------------------

def annotate_search_results_with_tags(beatmaps, user, include_predicted_toggle=False):
    beatmap_ids = list(beatmaps.values_list('id', flat=True))
    if not beatmap_ids:
        return beatmaps

    # Bulk-load TagApplications once for all beatmaps on the page
    tag_app_qs = (
        TagApplication.objects
        .filter(beatmap_id__in=beatmap_ids)
        .select_related('tag')
        .only('beatmap_id', 'user_id', 'tag__id', 'tag__name')
    )
    if not include_predicted_toggle:
        tag_app_qs = tag_app_qs.filter(user__isnull=False)

    beatmap_tag_counts = defaultdict(lambda: defaultdict(int))
    beatmap_predicted_names = defaultdict(set)
    user_applied_tags = defaultdict(set)

    for app in tag_app_qs:
        # Count user-applied for weights; predicted captured separately when included
        if app.user_id:
            beatmap_tag_counts[app.beatmap_id][app.tag] += 1
            if user.is_authenticated and app.user_id == getattr(user, 'id', None):
                user_applied_tags[app.beatmap_id].add(app.tag)
        elif include_predicted_toggle:
            # Track predicted tag names for later merge
            if getattr(app, 'tag', None):
                beatmap_predicted_names[app.beatmap_id].add(app.tag.name)

    # If we will include predicted tags, fetch all involved Tag objects in one query
    predicted_name_to_tag = {}
    if include_predicted_toggle and beatmap_predicted_names:
        all_predicted_names = set()
        for names in beatmap_predicted_names.values():
            all_predicted_names.update(names)
        if all_predicted_names:
            for tag in Tag.objects.filter(name__in=all_predicted_names).only('id', 'name'):
                predicted_name_to_tag[tag.name] = tag

    for bm in beatmaps:
        tags_counts = [
            {
                'tag': tag,
                'apply_count': cnt,
                'is_applied_by_user': tag in user_applied_tags.get(bm.id, set()),
            }
            for tag, cnt in beatmap_tag_counts.get(bm.id, {}).items()
        ]

        # Merge in predicted-only tags without extra queries
        if include_predicted_toggle:
            existing_names = set(t['tag'].name for t in tags_counts)
            add_names = beatmap_predicted_names.get(bm.id, set()) - existing_names
            if add_names:
                for name in add_names:
                    tag_obj = predicted_name_to_tag.get(name)
                    if tag_obj:
                        tags_counts.append({
                            'tag': tag_obj,
                            'apply_count': 0,
                            'is_applied_by_user': False,
                        })
        bm.tags_with_counts = sorted(tags_counts, key=lambda x: -x['apply_count'])

        # Backend-driven Find Similar Maps data
        top_tags = [tc['tag'].name for tc in bm.tags_with_counts[:10] if getattr(tc['tag'], 'name', None)]
        windows = compute_attribute_windows(bm)
        filters_to_apply = derive_filters_from_tags(top_tags)
        tags_query_string = ' '.join([f'"{t}"' if ' ' in t else t for t in top_tags])
        similar_query, extra_params = build_similar_maps_query(filters_to_apply, windows, tags_query_string)
        bm.similar_query = similar_query
        bm.similar_extra_params = extra_params
    return beatmaps


def parse_search_terms(query: str):
    '''Split query by whitespace, respecting quoted substrings.''' 
    return re.findall(r'[-.]?"[^"]+"|[-.]?[^"\s]+', query)


def build_query_conditions(beatmaps, search_terms, predicted_mode='include'):
    context = QueryContext(beatmaps)
    for op in (
        handle_attribute_queries,
        handle_quotes,
        handle_exclusion,
        handle_inclusion,
        handle_general_inclusion,
    ):
        search_terms = op(context, search_terms)
        if not context.beatmaps.exists():
            break
    if context.include_q:
        context.beatmaps = context.beatmaps.filter(context.include_q)
    if context.exclude_q:
        context.beatmaps = context.beatmaps.exclude(context.exclude_q)
    if context.required_tags:
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.required_tags)
    if context.include_tag_names:
        if predicted_mode == 'include':
            context.beatmaps = context.beatmaps.filter(tagapplication__tag__name__in=context.include_tag_names).distinct()
        elif predicted_mode == 'exclude':
            context.beatmaps = context.beatmaps.filter(
                tagapplication__tag__name__in=context.include_tag_names,
                tagapplication__user__isnull=False,
            ).distinct()
        elif predicted_mode == 'only':
            context.beatmaps = context.beatmaps.filter(
                tagapplication__tag__name__in=context.include_tag_names,
                tagapplication__user__isnull=True,
            ).distinct()
    if context.exclude_tags:
        context.beatmaps = context.beatmaps.exclude(tags__name__in=context.exclude_tags)
    return context.beatmaps, context.include_tag_names
