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
import datetime
import shlex
from collections import defaultdict

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
from nltk.stem import PorterStemmer
from ossapi.enums import ScoreType, GameMode, UserBeatmapType, UserLookupKey
from ossapi.mod import Mod

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
    FloatField,
    ExpressionWrapper,
    FilteredRelation,
)
from django.db.models.functions import Coalesce, Now, Greatest
from django.shortcuts import render, redirect
from django.urls import reverse
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, Tag, TagApplication, UserProfile, SavedSearch, ManiaKeyOption
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
    build_phrase_q,
)
from ..utils import QueryContext
# -------------------------- Search History Actions -------------------------- #

from django.views.decorators.http import require_POST
from django.http import HttpResponseBadRequest
import json as _json


@require_POST
def toggle_saved_search(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'auth required'}, status=403)
    try:
        hid = (request.POST.get('history_id') or '').strip()
        q = (request.POST.get('query') or '').strip()
        params = request.POST.get('params_json')
        history = request.session.get('search_history', [])
        rec = next((r for r in history if r.get('id') == hid), None)
        if rec:
            q = rec.get('query') or ''
            params = _json.dumps(rec.get('params') or {}, sort_keys=True)
        else:
            try:
                params = _json.dumps(_json.loads(params or '{}'), sort_keys=True)
            except Exception:
                params = _json.dumps({}, sort_keys=True)

        existing = SavedSearch.objects.filter(user=request.user, query=q, params_json=params).first()
        if existing:
            existing.delete()
            return JsonResponse({'saved': False, 'params_json': params})
        cleaned_query = (q or '').strip()
        title = cleaned_query[:25] if cleaned_query else 'Saved query'
        ss = SavedSearch.objects.create(user=request.user, title=title[:255], query=q, params_json=params)
        return JsonResponse({'saved': True, 'saved_id': ss.id, 'title': ss.title, 'params_json': params, 'query': q})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@require_POST
def update_saved_search_title(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'auth required'}, status=403)
    try:
        sid = int((request.POST.get('saved_id') or '0').strip())
        title = (request.POST.get('title') or '').strip() or 'Search'
        ss = SavedSearch.objects.filter(id=sid, user=request.user).first()
        if not ss:
            return JsonResponse({'error': 'not found'}, status=404)
        ss.title = title[:255]
        ss.save(update_fields=['title', 'updated_at'])
        return JsonResponse({'ok': True, 'title': ss.title})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@require_POST
def delete_saved_search(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'auth required'}, status=403)
    try:
        sid = int((request.POST.get('saved_id') or '0').strip())
        ss = SavedSearch.objects.filter(id=sid, user=request.user).first()
        if not ss:
            return JsonResponse({'error': 'not found'}, status=404)
        ss.delete()
        return JsonResponse({'ok': True})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
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

    def format_slider_value(value: float | int | str) -> str:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        text = f'{num:.2f}'
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text or '0'

    def apply_toggle(snapshot: dict, key: str, active, value: str):
        if active:
            snapshot[key] = value
        else:
            snapshot.pop(key, None)

    def parse_query_with_quotes(raw_query: str):
        '''Split query, treating quoted substrings as single tokens.'''
        lexer = shlex.shlex(raw_query, posix=True)
        lexer.whitespace_split = True
        lexer.quotes = '\"\''
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
            sanitized = term.strip('\"\'')
            stemmed.add(stem_phrase(sanitized) if ' ' in sanitized else stem_word(sanitized))
        return stemmed

    def identify_exact_match_tags(include_like_tags, parsed_terms):
        # Normalize parsed terms by stripping quotes and operator prefixes like '.' or '-'
        raw_terms = {
            (term or '').strip('\"\'').strip().lower().lstrip('.-')
            for term, _ in parsed_terms
        }
        return {
            tag for tag in include_like_tags
            if (tag or '').strip('\"\'').strip().lower() in raw_terms
        }

    def derive_simple_phrase(parsed_terms):
        tokens = []
        has_special = False
        attribute_prefixes = ('ar', 'cs', 'od', 'hp', 'bpm', 'length', 'count', 'fav', 'pp', 'nm', 'hd', 'hr', 'dt', 'ht', 'ez', 'fl', 'year')
        for raw_term, _ in parsed_terms:
            cleaned = (raw_term or '').strip().strip('\'"')
            if not cleaned:
                continue
            lower = cleaned.lower()
            special = cleaned.startswith(('.', '-')) or any(ch in cleaned for ch in ['=', '>', '<', ':']) or any(lower.startswith(pref) for pref in attribute_prefixes)
            if special:
                has_special = True
                continue
            tokens.append(cleaned)
        if has_special or len(tokens) < 2:
            return ''
        return ' '.join(tokens)

    def extract_direct_ids(raw_query: str):
        val = (raw_query or '').strip()
        if not val:
            return []
        if val.isdigit():
            return [val]
        lowered = val.lower()
        if lowered.startswith('http://') or lowered.startswith('https://'):
            numbers = re.findall(r'(\d+)', val)
            if not numbers:
                return []
            # Prefer tail (beatmap id) but include previous number (set id) if present.
            ordered = []
            for candidate in numbers[-2:]:
                if candidate not in ordered:
                    ordered.append(candidate)
            return ordered
        return []

    def build_params_snapshot(query_dict, query_value, active_mode):
        params_copy = query_dict.copy()
        if 'page' in params_copy:
            del params_copy['page']
        snapshot = {}
        for key, values in params_copy.lists():
            if not values:
                continue
            snapshot[key] = values[-1]
        snapshot['query'] = query_value
        if active_mode:
            snapshot.setdefault('mode', active_mode)
        return snapshot

    def saved_label_from(title, query_value, limit=25):
        base_title = (title or '').strip()
        # Handle query_value being a list (from QueryDict serialization)
        if isinstance(query_value, list):
            query_value = query_value[-1] if query_value else ''
        normalized = (query_value or '').strip()
        if base_title and base_title.lower() not in ['search', 'saved query'] and base_title != normalized:
            return base_title
        display = normalized or '(no query)'
        if len(display) > limit:
            truncated = max(limit - 3, 1)
            return display[:truncated] + '...'
        return display

    def annotate_and_order_beatmaps(qs, include_tags, exact_tags, sort, predicted_mode):
        # Use a single filtered relation for positive tag applications to reduce join cost
        qs = qs.annotate(ta_pos=FilteredRelation('tagapplication', condition=Q(tagapplication__true_negative=False)))

        # Gate to beatmaps that have at least one of include_tags, honoring predicted toggle,
        # but DO NOT restrict the join used for weighting annotations.
        if include_tags:
            if predicted_mode == 'include':
                qs = qs.annotate(_include_match=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=include_tags), distinct=True)).filter(_include_match__gt=0)
            elif predicted_mode == 'exclude':
                qs = qs.annotate(_include_match=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=include_tags, ta_pos__user__isnull=False), distinct=True)).filter(_include_match__gt=0)
            elif predicted_mode == 'only':
                qs = qs.annotate(_include_match=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=include_tags, ta_pos__user__isnull=True), distinct=True)).filter(_include_match__gt=0)
                qs = qs.annotate(_has_user_pos=Count('ta_pos__id', filter=Q(ta_pos__user__isnull=False))).filter(_has_user_pos=0)

        # Count total tags per map; when excluding predictions, count only user-applied
        if predicted_mode == 'include':
            total_tag_count_expr = Count('ta_pos__tag', distinct=True)
        else:  # exclude and only: count only user-applied applications for denominator
            total_tag_count_expr = Count('ta_pos__tag', filter=Q(ta_pos__user__isnull=False), distinct=True)
        if sort == 'tag_weight':
            # Weight factor for predicted tags (0.5 when included/only, else 0)
            p_w = Value(0.5 if predicted_mode in ['include', 'only'] else 0.0)

            qs = (
                qs.annotate(
                    # Per-beatmap total and matched tag application counts (non-distinct)
                    total_app_count=Count('ta_pos__id'),
                    matched_exact_app_count=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=exact_tags)),
                    # Per-beatmap distinct tag name counts
                    total_distinct_count=Count('ta_pos__tag', distinct=True),
                    matched_exact_distinct_count=Count('ta_pos__tag', filter=Q(ta_pos__tag__name__in=exact_tags), distinct=True),
                    # User vs predicted counts
                    u_tag_match_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=include_tags) & Q(ta_pos__user__isnull=False)),
                        distinct=True,
                    ),
                    p_tag_match_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=include_tags) & Q(ta_pos__user__isnull=True)),
                        distinct=True,
                    ),
                    # Non-exact distinct matches (for numerator-only spending)
                    u_nonexact_match_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=include_tags) & ~Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=False)),
                        distinct=True,
                    ),
                    p_nonexact_match_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=include_tags) & ~Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=True)),
                        distinct=True,
                    ),
                    u_exact_total_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=False)),
                    ),
                    p_exact_total_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=True)),
                    ),
                    u_exact_distinct_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=False)),
                        distinct=True,
                    ),
                    p_exact_distinct_count=Count(
                        'ta_pos__tag',
                        filter=(Q(ta_pos__tag__name__in=exact_tags) & Q(ta_pos__user__isnull=True)),
                        distinct=True,
                    ),
                    total_tag_count=total_tag_count_expr,
                )
                .annotate(
                    # Unweighted total matched distinct tags (for denominator diagnostics)
                    matched_distinct_total=(
                        (F('u_tag_match_count') + F('p_tag_match_count')) if predicted_mode in ['include', 'only'] else F('u_tag_match_count')
                    ),
                    # Weighted components: predicted scaled down by p_w
                    weighted_exact_distinct=F('u_exact_distinct_count') + F('p_exact_distinct_count') * p_w,
                    weighted_exact_total=F('u_exact_total_count') + F('p_exact_total_count') * p_w,
                    # Spend exact distinct first; only count extra applications beyond first towards exact_total
                    weighted_exact_total_surplus=(F('u_exact_total_count') - F('u_exact_distinct_count')) + (F('p_exact_total_count') - F('p_exact_distinct_count')) * p_w,
                    # Only non-exact matched distinct tags contribute here to avoid overlap with exacts
                    weighted_tag_match=F('u_nonexact_match_count') + F('p_nonexact_match_count') * p_w,
                )
                .annotate(
                    tag_miss_match_count=Value(len(exact_tags), output_field=IntegerField()) - F('matched_exact_distinct_count'),
                    tag_surplus_count_distinct=F('total_distinct_count') - F('matched_exact_distinct_count'),
                    tag_surplus_count=(F('total_app_count') - F('matched_exact_app_count')) - F('tag_surplus_count_distinct'),
                    tag_weight=(
                        (F('weighted_exact_distinct') * Value(1.5) + # distinct exact tag names (first copy only)
                         F('weighted_exact_total_surplus') * Value(2.12) + # extra apps beyond first per exact tag
                         F('weighted_tag_match') * Value(0.2)) / # distinct non-exact tag matches
                        (
                            (F('tag_miss_match_count') * Value(1.5)) + # distinct search tags not present on map
                            (F('tag_surplus_count_distinct') * Value(0.5)) + # distinct extra tag names on map not in the search
                            (F('tag_surplus_count') * Value(2.12)) + # extra duplicate applications beyond first of tags not in the search
                            Value(1.0) # base to avoid division by zero when perfect matches and no surplus
                        )
                    ),
                )
                .order_by('-tag_weight')
            )
            
        else:
            from django.db.models import FloatField, ExpressionWrapper
            import datetime
            qs = (
                qs.annotate(
                    base_popularity=F('favourite_count') * Value(0.02) + F('playcount') * Value(0.0001),
                    years_since_update_raw=ExpressionWrapper(
                        (Now() - F('last_updated')) / Value(datetime.timedelta(days=365.25)),
                        output_field=FloatField(),
                    ),
                )
                .annotate(
                    years_since_update=Greatest(Coalesce(F('years_since_update_raw'), Value(1.0)), Value(1.0)),
                    popularity=F('base_popularity') / F('years_since_update'),
                )
                .order_by('-popularity')
            )
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
    user_default_mode = 'osu'
    if request.user.is_authenticated:
        try:
            user_settings = getattr(request.user, 'settings', None)
            if user_settings and getattr(user_settings, 'default_mode', None):
                user_default_mode = user_settings.default_mode
        except Exception:
            user_default_mode = 'osu'
    selected_mode = (request.GET.get('mode') or user_default_mode or 'osu').strip().lower()
    star_min_raw = (request.GET.get('star_min', '0') or '0').strip()
    star_max_raw = (request.GET.get('star_max', '10') or '10').strip()
    star_min = star_min_raw
    star_max = star_max_raw
    sort = request.GET.get('sort', '')
    exclude_player = (request.GET.get('exclude_player') or 'none').strip().lower()
    fetch_exclude_now = (request.GET.get('fetch_exclude_now') or '1').strip()
    requested_keys = (request.GET.get('keys') or '').strip()
    params_snapshot = build_params_snapshot(request.GET, query, selected_mode)
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
        star_min = max(float(star_min_raw), 0)
    except ValueError:
        star_min = 0.0
        star_min_raw = '0'
    try:
        star_max = float(star_max_raw)
        if star_max < star_min:
            star_max = 10.0
            star_max_raw = '10'
    except ValueError:
        star_max = 10.0
        star_max_raw = '10'
    star_min_value_str = format_slider_value(star_min)
    star_max_value_str = format_slider_value(star_max)

    MODE_MAPPING = {'osu': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
    GAME_MODE_ENUM = {
        'osu': GameMode.OSU,
        'taiko': GameMode.TAIKO,
        'catch': GameMode.CATCH,
        'mania': GameMode.MANIA,
    }
    mapped_mode = MODE_MAPPING.get(selected_mode, 'osu')
    normalized_mode = Tag.normalize_mode(mapped_mode)

    beatmaps = Beatmap.objects.filter(mode__iexact=mapped_mode)
    beatmaps = beatmaps.filter(difficulty_rating__gte=star_min)
    if star_max < 15:
        beatmaps = beatmaps.filter(difficulty_rating__lte=star_max)
    direct_id_values = extract_direct_ids(query)
    direct_id_q = None
    if direct_id_values:
        direct_id_q = Q()
        for val in direct_id_values:
            direct_id_q |= Q(beatmap_id=str(val)) | Q(beatmapset_id=str(val))
    if direct_id_q:
        beatmaps = beatmaps.filter(direct_id_q)

    mania_key_options = []
    selected_keys = 'any'
    if mapped_mode == 'mania':
        mania_qs = list(ManiaKeyOption.objects.order_by('value'))
        mania_key_options = [
            {'value': opt.value_string, 'label': opt.label}
            for opt in mania_qs
        ]
        mania_value_strings = [opt['value'] for opt in mania_key_options]
        default_user_keys = 'any'
        if request.user.is_authenticated:
            try:
                default_user_keys = getattr(request.user.settings, 'default_mania_keys', 'any') or 'any'
            except Exception:
                default_user_keys = 'any'
        selected_keys = requested_keys or default_user_keys
        if selected_keys not in mania_value_strings and selected_keys != 'any':
            selected_keys = 'any'
        if selected_keys != 'any':
            try:
                beatmaps = beatmaps.filter(cs=float(selected_keys))
            except ValueError:
                selected_keys = 'any'
    else:
        selected_keys = 'any'

    # Exclude user's Top plays or Favourites if requested
    if exclude_player in ['top50', 'top100', 'fav']:
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
                if exclude_player in ['top50', 'top100']:
                    try:
                        # Cache by mode and limit to avoid repeated fetches during pagination/sorting
                        top_limit = 50 if exclude_player == 'top50' else 100
                        cache_key = f'exclude_top_ids_{selected_mode}_{top_limit}'
                        cache_ts_key = f'{cache_key}_ts'
                        ids = request.session.get(cache_key) or []
                        ts = request.session.get(cache_ts_key) or 0
                        now = int(time.time())
                        if fetch_exclude_now == '1' and (not ids or (now - int(ts)) > 600):
                            gm = GAME_MODE_ENUM.get(selected_mode, GameMode.OSU)
                            scores = api.user_scores(int(osu_id), ScoreType.BEST, mode=gm, limit=top_limit)
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
    search_term_values = [] if direct_id_q else [t[0] for t in parsed_terms]
    phrase_terms = []
    if not direct_id_q:
        simple_phrase = derive_simple_phrase(parsed_terms)
        if simple_phrase:
            phrase_terms.append(simple_phrase)
    beatmaps, include_tags, required_tags, pp_calc_params = build_query_conditions(beatmaps, search_term_values, predicted_mode, phrase_terms)

    stemmed_terms = process_search_terms(parsed_terms)
    # Combine include + required tags for weighting and exact-match purposes
    include_like_tags = sorted(set(include_tags or []) | set(required_tags or []))
    exact_tags = identify_exact_match_tags(include_like_tags, parsed_terms)

    if sort not in ['tag_weight', 'popularity']:
        if not request.user.is_authenticated:
            # For unauthenticated users, prefer tag_weight by default
            sort = 'tag_weight'
        else:
            # Default depends on query presence: tag_weight when query present, else popularity
            sort = 'tag_weight' if include_like_tags else 'popularity'

    params_snapshot['query'] = query
    params_snapshot['mode'] = selected_mode
    params_snapshot['star_min'] = star_min_value_str
    params_snapshot['star_max'] = star_max_value_str
    params_snapshot['exclude_player'] = exclude_player
    params_snapshot['include_predicted'] = predicted_mode
    params_snapshot['sort'] = sort
    apply_toggle(params_snapshot, 'status_ranked', status_ranked, 'ranked')
    apply_toggle(params_snapshot, 'status_loved', status_loved, 'loved')
    apply_toggle(params_snapshot, 'status_unranked', status_unranked, 'unranked')
    if mapped_mode == 'mania' and selected_keys and selected_keys != 'any':
        params_snapshot['keys'] = selected_keys
    else:
        params_snapshot.pop('keys', None)
    current_params_json = _json.dumps(params_snapshot, sort_keys=True)

    if include_like_tags:
        # Use exact token-matched tags for weighting to avoid substring expansions
        # affecting scores when '.' is used. Gating was already applied earlier.
        beatmaps = annotate_and_order_beatmaps(beatmaps, exact_tags, exact_tags, sort, predicted_mode)
    else:
        # When no include tags are specified, still respect the predicted toggle:
        # - include: show all
        # - exclude: only maps with user-applied tags
        # - only: only maps that have predicted tags
        if predicted_mode == 'exclude':
            beatmaps = beatmaps.annotate(_has_user_pos=Count('tagapplication', filter=Q(tagapplication__true_negative=False, tagapplication__user__isnull=False))).filter(_has_user_pos__gt=0).distinct()
        elif predicted_mode == 'only':
            beatmaps = beatmaps.annotate(_has_user_pos=Count('tagapplication', filter=Q(tagapplication__true_negative=False, tagapplication__user__isnull=False))).filter(_has_user_pos=0).distinct()

        beatmaps = (
            beatmaps.annotate(
                total_tag_apply_count=Count('tagapplication', filter=Q(tagapplication__true_negative=False)),
                tag_weight=F('total_tag_apply_count'),
                base_popularity=F('favourite_count') * Value(0.02) + F('playcount') * Value(0.0001),
                years_since_update_raw=ExpressionWrapper(
                    (Now() - F('last_updated')) / Value(datetime.timedelta(days=365.25)),
                    output_field=FloatField(),
                ),
            )
            .annotate(
                years_since_update=Greatest(Coalesce(F('years_since_update_raw'), Value(1.0)), Value(1.0)),
                popularity=F('base_popularity') / F('years_since_update'),
            )
        )
        beatmaps = beatmaps.order_by('-' + sort) if sort in ['tag_weight', 'popularity'] else beatmaps.order_by('-favourite_count', '-playcount')

    # Save toggle into request so downstream helpers can read it via thread locals
    # Expose predicted_mode via context only

    # Lightweight queryset hints to avoid unnecessary payloads/N+1s
    beatmaps = beatmaps.prefetch_related('genres')

    # Server-side paginate to a modest page size to reduce template rendering cost
    paginator = Paginator(beatmaps, 10)
    page_obj = paginator.get_page(request.GET.get('page'))



    annotate_search_results_with_tags(page_obj.object_list, request.user, predicted_mode in ['include', 'only'])

    # Attach derived, lightweight display fields only
    seen_high_confidence = False
    threshold_set = False
    for bm in page_obj.object_list:
        try:
            # Import lazily to avoid circular on module import
            from .shared import format_length_hms  # type: ignore
            bm.length_formatted = format_length_hms(bm.total_length)
        except Exception:
            bm.length_formatted = None

        weight = getattr(bm, 'tag_weight', None)
        if weight is not None:
            if weight >= 1.0:
                seen_high_confidence = True
            if not threshold_set and seen_high_confidence and weight < 1.0:
                bm.tag_weight_threshold_marker = True
                threshold_set = True
            else:
                bm.tag_weight_threshold_marker = False
        else:
            bm.tag_weight_threshold_marker = False

    # Record search history in session for authenticated users (simple, per-browser)
    # Ignore empty queries
    try:
        if request.user.is_authenticated and (query or '').strip():
            history = request.session.get('search_history', [])
            import uuid, time as _time
            record = {
                'id': str(uuid.uuid4()),
                'query': query,
                'params': dict(params_snapshot),
                'ts': int(_time.time()),
                'favorite': False,
            }
            # De-duplicate identical (same query and params) older entries
            new_hist = [r for r in history if not (r.get('query') == record['query'] and r.get('params') == record['params'])]
            new_hist.insert(0, record)
            request.session['search_history'] = new_hist[:50]
            request.session.modified = True
    except Exception:
        pass

    # Build analytics context for client-side logging (no PII)
    try:
        analytics_context = {
            'query': query,
            'tags': include_like_tags,
            'results_count': paginator.count,
            'sort': sort,
            'predicted_mode': predicted_mode,
            'mode': normalized_mode,
            'flags': {
                'status_ranked': bool(status_ranked),
                'status_loved': bool(status_loved),
                'status_unranked': bool(status_unranked),
                'mode': normalized_mode,
            },
        }
    except Exception:
        analytics_context = {}

    analytics_tags = sorted(exact_tags)
    try:
        analytics_context['tags'] = analytics_tags
    except Exception:
        analytics_context = {'tags': analytics_tags}

    saved_search_options = []
    current_saved_search_id = None
    if request.user.is_authenticated:
        saved_records = list(
            SavedSearch.objects
            .filter(user=request.user)
            .order_by('-updated_at')
            .only('id', 'title', 'query', 'params_json')
        )
        for record in saved_records:
            try:
                payload = _json.loads(record.params_json or '{}')
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}
            payload.setdefault('query', record.query or '')
            qs_string = urlencode(payload, doseq=True)
            display_query = payload.get('query') or record.query or ''
            saved_search_options.append({
                'id': record.id,
                'label': saved_label_from(record.title, display_query),
                'qs': qs_string,
            })
            if current_saved_search_id is None and (record.params_json or '') == current_params_json:
                current_saved_search_id = record.id

    return render(
        request,
        'search_results.html',
        {
            'beatmaps': page_obj,
            'query': query,
            'active_mode': selected_mode,
            'star_min': star_min,
            'star_max': star_max,
            'star_min_value': star_min_value_str,
            'star_max_value': star_max_value_str,
            'sort': sort,
            'status_ranked': status_ranked,
            'status_loved': status_loved,
            'status_unranked': status_unranked,
            'include_predicted': predicted_mode,
            'pp_calc_params': pp_calc_params,
            # Analytics context
            'include_like_tags': include_like_tags,
            'results_total': paginator.count,
            'analytics_context': analytics_context | {'tags': analytics_tags},
            'saved_searches': saved_search_options,
            'current_saved_search_id': current_saved_search_id,
            'current_search_params_json': current_params_json,
            'mania_key_options': mania_key_options,
            'selected_keys': selected_keys,
        },
    )


# -------------------------- Preset Search Views -------------------------- #

def _resolve_osu_id_from_request(request):
    try:
        osu_id = request.session.get('osu_id')
        if not osu_id and request.user.is_authenticated:
            osu_id = (
                UserProfile.objects
                .filter(user=request.user)
                .values_list('osu_id', flat=True)
                .first()
            )
        return int(osu_id) if osu_id else None
    except Exception:
        return None


def _compute_player_top_tags_and_star_window(osu_id: int, source: str, selected_mode: str):
    MODE_MAPPING = {'osu': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
    GAME_MODE_ENUM = {
        'osu': GameMode.OSU,
        'taiko': GameMode.TAIKO,
        'catch': GameMode.CATCH,
        'mania': GameMode.MANIA,
    }
    mapped_mode = MODE_MAPPING.get(selected_mode, 'osu')
    gm = GAME_MODE_ENUM.get(selected_mode, GameMode.OSU)

    beatmaps_for_player = Beatmap.objects.none()
    try:
        if source == 'top':
            scores = api.user_scores(int(osu_id), ScoreType.BEST, mode=gm, limit=10)
            ids = [str(getattr(s.beatmap, 'id', '')) for s in scores if getattr(s, 'beatmap', None)]
            ids = [i for i in ids if i]
            if ids:
                beatmaps_for_player = Beatmap.objects.filter(beatmap_id__in=ids, mode__iexact=mapped_mode)
        else:  # 'fav'
            fav_sets = api.user_beatmaps(int(osu_id), UserBeatmapType.FAVOURITE, limit=40)
            set_ids = [str(getattr(bs, 'id', '')) for bs in fav_sets]
            set_ids = [i for i in set_ids if i]
            if set_ids:
                beatmaps_for_player = Beatmap.objects.filter(beatmapset_id__in=set_ids, mode__iexact=mapped_mode)
    except Exception:
        beatmaps_for_player = Beatmap.objects.none()

    # Derive top tags (by tag application counts)
    top_tags = []
    if beatmaps_for_player.exists():
        rows = (
            TagApplication.objects
            .filter(beatmap__in=beatmaps_for_player)
            .values('tag__name')
            .annotate(c=Count('id'))
            .order_by('-c')[:15]
        )
        top_tags = [r['tag__name'] for r in rows if r['tag__name']][:15]

    # Compute a reasonable star window around the median
    star_min_val = None
    star_max_val = None
    try:
        stars = list(beatmaps_for_player.values_list('difficulty_rating', flat=True))
        stars = [float(s) for s in stars if s is not None]
        if stars:
            stars_sorted = sorted(stars)
            n = len(stars_sorted)
            median_star = stars_sorted[n//2] if n % 2 == 1 else (stars_sorted[n//2 - 1] + stars_sorted[n//2]) / 2.0
            delta = max(0.5, float(median_star) * 0.10)
            star_min_val = max(0.0, float(median_star) - delta)
            star_max_val = min(15.0, float(median_star) + delta)
    except Exception:
        star_min_val, star_max_val = None, None

    return top_tags, star_min_val, star_max_val


def preset_search_farm(request):
    selected_mode = (request.GET.get('mode') or 'osu').strip().lower()
    # Optional override from query param to support Statistics page user
    osu_id = None
    user_override = (request.GET.get('user') or '').strip()
    if user_override:
        try:
            if user_override.isdigit():
                u = api.user(int(user_override), key=UserLookupKey.ID)
            else:
                u = api.user(user_override, key=UserLookupKey.USERNAME)
            osu_id = int(getattr(u, 'id', None) or 0) or None
        except Exception:
            osu_id = None
    if not osu_id:
        osu_id = _resolve_osu_id_from_request(request)
    if not osu_id:
        return redirect('search_results')

    top_tags, star_min_val, star_max_val = _compute_player_top_tags_and_star_window(osu_id, 'top', selected_mode)
    tags_query_string = ' '.join([
        ('.' if (t or '').strip().lower() == 'farm' else '') + (f'"{t}"' if ' ' in (t or '') else (t or ''))
        for t in top_tags
    ])

    # Derive PP constraints based on user's top plays mod distribution
    def _derive_farm_pp_tokens(osu_id_int: int, mode_key: str):
        try:
            MODE_MAPPING = {'osu': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
            GAME_MODE_ENUM_LOCAL = {
                'osu': GameMode.OSU,
                'taiko': GameMode.TAIKO,
                'catch': GameMode.CATCH,
                'mania': GameMode.MANIA,
            }
            gm = GAME_MODE_ENUM_LOCAL.get(mode_key, GameMode.OSU)
            scores = api.user_scores(int(osu_id_int), ScoreType.BEST, mode=gm, limit=10)
        except Exception:
            return []

        if not scores:
            return []

        # Count meaningful mod families individually and track NM explicitly
        mod_families = ['HD', 'HR', 'DT', 'HT', 'EZ', 'FL']
        family_counts = {k: 0 for k in mod_families}
        nm_count = 0
        n = 0
        top_pp_val = None
        for s in scores:
            try:
                n += 1
                # Track top pp
                spp = getattr(s, 'pp', None)
                if spp is not None:
                    try:
                        v = float(spp)
                        if top_pp_val is None or v > top_pp_val:
                            top_pp_val = v
                    except Exception:
                        pass

                mods_val = getattr(s, 'mods', None)
                families_for_score = set()
                if mods_val:
                    if Mod.HD in mods_val:
                        families_for_score.add('HD')
                    if Mod.HR in mods_val:
                        families_for_score.add('HR')
                    if (Mod.DT in mods_val) or (Mod.NC in mods_val):
                        families_for_score.add('DT')
                    if Mod.HT in mods_val:
                        families_for_score.add('HT')
                    if Mod.EZ in mods_val:
                        families_for_score.add('EZ')
                    if Mod.FL in mods_val:
                        families_for_score.add('FL')
                # If no meaningful families detected, treat as NM
                if not families_for_score:
                    nm_count += 1
                for fam in families_for_score:
                    if fam in family_counts:
                        family_counts[fam] += 1
            except Exception:
                continue

        if n == 0 or top_pp_val is None:
            return []

        # Priority rules (top 10 window):
        # 1) DT >= 4 -> DT
        # 2) (EZ + FL + HT) >= 4 -> pick the most frequent among EZ/FL/HT
        # 3) HR >= 4 (and DT < 4 by rule order) -> HR
        # 4) HD >= 4 -> HD
        # 5) NM >= 7 -> NM
        # 6) Fallback: pick most frequent by count with precedence DT > (EZ/FL/HT) > HR > HD > NM; else generic PP.
        dt_count = family_counts.get('DT', 0)
        hr_count = family_counts.get('HR', 0)
        hd_count = family_counts.get('HD', 0)
        ht_count = family_counts.get('HT', 0)
        ez_count = family_counts.get('EZ', 0)
        fl_count = family_counts.get('FL', 0)

        chosen_attr = None
        if dt_count >= 4:
            chosen_attr = 'DT'
        else:
            low_speed_total = ez_count + fl_count + ht_count
            if low_speed_total >= 4:
                # Choose the most common among EZ/FL/HT (tie-breaker EZ > FL > HT for stability)
                low_speed_counts = [('EZ', ez_count), ('FL', fl_count), ('HT', ht_count)]
                low_speed_counts.sort(key=lambda kv: (-kv[1], ['EZ', 'FL', 'HT'].index(kv[0])))
                if low_speed_counts[0][1] > 0:
                    chosen_attr = low_speed_counts[0][0]
            elif hr_count >= 4:
                chosen_attr = 'HR'
            elif hd_count >= 4:
                chosen_attr = 'HD'
            elif nm_count >= 7:
                chosen_attr = 'NM'
            else:
                # Fallback by max count with precedence
                precedence = {'DT': 5, 'EZ': 4, 'FL': 4, 'HT': 4, 'HR': 3, 'HD': 2, 'NM': 1}
                all_counts = {
                    'DT': dt_count,
                    'EZ': ez_count,
                    'FL': fl_count,
                    'HT': ht_count,
                    'HR': hr_count,
                    'HD': hd_count,
                    'NM': nm_count,
                }
                # Pick the family with highest count; break ties by precedence
                best = sorted(all_counts.items(), key=lambda kv: (-kv[1], -precedence.get(kv[0], 0)))
                if best and best[0][1] > 0:
                    chosen_attr = best[0][0]

        lower = max(0.0, top_pp_val * 0.95)
        upper = top_pp_val * 1.3

        # Build tokens using chosen attribute or generic PP if none chosen
        attr = chosen_attr if chosen_attr else 'PP'
        tokens = [f'{attr}>={lower:.0f}', f'{attr}<={upper:.0f}']
        return tokens

    pp_tokens = _derive_farm_pp_tokens(int(osu_id), selected_mode)

    # Start from existing GET params to preserve user selections
    params = request.GET.copy()

    # Normalize and override only what's needed
    params['mode'] = selected_mode
    params['fetch_exclude_now'] = '1'

    # Always start farm preset on tag_weight; user can switch afterward
    params['sort'] = 'tag_weight'

    # Respect user's exclude selection; if none/absent, use top100
    exclude_player_val = (params.get('exclude_player') or 'none').strip().lower()
    if exclude_player_val in ['', 'none']:
        params['exclude_player'] = 'top100'

    # Preserve star range if provided; otherwise use computed window
    if not params.get('star_min') and star_min_val is not None:
        params['star_min'] = f"{star_min_val:.2f}"
    if not params.get('star_max') and star_max_val is not None:
        params['star_max'] = f"{star_max_val:.2f}"

    # Do not force status defaults; keep whatever the user had (including none)

    # Replace current tag input with generated tags, plus PP constraints
    query_parts = []
    if pp_tokens:
        query_parts.extend(pp_tokens)
    if tags_query_string:
        query_parts.append(tags_query_string)
    params['query'] = ' '.join(query_parts)

    # Reset pagination
    if 'page' in params:
        del params['page']

    url = reverse('search_results') + ('?' + params.urlencode())
    return redirect(url)


def preset_search_new_favorites(request):
    selected_mode = (request.GET.get('mode') or 'osu').strip().lower()
    # Optional override from query param to support Statistics page user
    osu_id = None
    user_override = (request.GET.get('user') or '').strip()
    if user_override:
        try:
            if user_override.isdigit():
                u = api.user(int(user_override), key=UserLookupKey.ID)
            else:
                u = api.user(user_override, key=UserLookupKey.USERNAME)
            osu_id = int(getattr(u, 'id', None) or 0) or None
        except Exception:
            osu_id = None
    if not osu_id:
        osu_id = _resolve_osu_id_from_request(request)
    if not osu_id:
        return redirect('search_results')

    top_tags, star_min_val, star_max_val = _compute_player_top_tags_and_star_window(osu_id, 'fav', selected_mode)
    # Limit to top 15 tags for favorites-based discovery
    top_tags = (top_tags or [])[:15]
    tags_query_string = ' '.join([f'"{t}"' if ' ' in t else t for t in top_tags])

    # Start from existing GET params to preserve user selections
    params = request.GET.copy()

    # Normalize and override only what's needed
    params['mode'] = selected_mode
    params['fetch_exclude_now'] = '1'

    # Always start favorites preset on tag_weight; user can switch afterward
    params['sort'] = 'tag_weight'

    # Respect user's exclude selection; if none/absent, use fav
    exclude_player_val = (params.get('exclude_player') or 'none').strip().lower()
    if exclude_player_val in ['', 'none']:
        params['exclude_player'] = 'fav'

    # Preserve star range if provided; otherwise use computed window
    if not params.get('star_min') and star_min_val is not None:
        params['star_min'] = f"{star_min_val:.2f}"
    if not params.get('star_max') and star_max_val is not None:
        params['star_max'] = f"{star_max_val:.2f}"

    # Do not force status defaults; keep whatever the user had (including none)

    # Replace current tag input with generated tags (do not merge)
    params['query'] = tags_query_string

    # Reset pagination
    if 'page' in params:
        del params['page']

    url = reverse('search_results') + ('?' + params.urlencode())
    return redirect(url)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def annotate_search_results_with_tags(beatmaps, user, include_predicted_toggle=False):
    beatmap_ids = list(beatmaps.values_list('id', flat=True))
    if not beatmap_ids:
        return beatmaps

    # Bulk-load TagApplications once for all beatmaps on the page
    tag_app_qs = (
        TagApplication.objects
        .filter(beatmap_id__in=beatmap_ids, true_negative=False)
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
                beatmap_predicted_names[app.beatmap_id].add((app.tag.name, Tag.normalize_mode(app.tag.mode)))

    # If we will include predicted tags, fetch all involved Tag objects in one query
    predicted_name_to_tag = defaultdict(dict)
    if include_predicted_toggle and beatmap_predicted_names:
        all_predicted_pairs = set()
        for names in beatmap_predicted_names.values():
            all_predicted_pairs.update(names)
        if all_predicted_pairs:
            names = {name for name, _ in all_predicted_pairs}
            modes = {mode for _, mode in all_predicted_pairs}
            for tag in Tag.objects.filter(name__in=names, mode__in=modes).only('id', 'name', 'mode'):
                normalized = Tag.normalize_mode(tag.mode)
                predicted_name_to_tag[normalized][tag.name] = tag

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
            existing_ids = set(t['tag'].id for t in tags_counts)
            add_names = beatmap_predicted_names.get(bm.id, set())
            if add_names:
                normalized_mode_bm = Tag.normalize_mode(bm.mode)
                for name, mode in add_names:
                    tag_obj = predicted_name_to_tag.get(mode, {}).get(name)
                    if tag_obj and tag_obj.id not in existing_ids and mode == normalized_mode_bm:
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


def build_query_conditions(beatmaps, search_terms, predicted_mode='include', phrase_terms=None):
    context = QueryContext(beatmaps)
    if phrase_terms:
        context.metadata_phrases.extend([p for p in phrase_terms if p])
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
        # Require ALL '.'-prefixed tags to be present (AND semantics), excluding true negatives
        context.beatmaps = context.beatmaps.annotate(ta_pos=FilteredRelation('tagapplication', condition=Q(tagapplication__true_negative=False)))
        req_filter = Q(ta_pos__tag__name__in=context.required_tags)
        if predicted_mode == 'exclude':
            req_filter &= Q(ta_pos__user__isnull=False)
        elif predicted_mode == 'only':
            req_filter &= Q(ta_pos__user__isnull=True)
        context.beatmaps = (
            context.beatmaps
            .annotate(
                num_required_tags=Count('ta_pos__tag', filter=req_filter, distinct=True)
            )
            .filter(num_required_tags=len(context.required_tags))
        )
    if context.include_tag_names:
        # Gate to maps that have at least one of the include tags, without
        # restricting the join rows used later for weighting annotations.
        context.beatmaps = context.beatmaps.annotate(ta_pos=FilteredRelation('tagapplication', condition=Q(tagapplication__true_negative=False)))
        if predicted_mode == 'include':
            context.beatmaps = context.beatmaps.annotate(
                _inc_cnt=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=context.include_tag_names), distinct=True)
            ).filter(_inc_cnt__gt=0)
        elif predicted_mode == 'exclude':
            context.beatmaps = context.beatmaps.annotate(
                _inc_cnt=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=context.include_tag_names, ta_pos__user__isnull=False), distinct=True)
            ).filter(_inc_cnt__gt=0)
        elif predicted_mode == 'only':
            context.beatmaps = context.beatmaps.annotate(
                _inc_cnt=Count('ta_pos__id', filter=Q(ta_pos__tag__name__in=context.include_tag_names, ta_pos__user__isnull=True), distinct=True),
                _has_user_pos=Count('ta_pos__id', filter=Q(ta_pos__user__isnull=False))
            ).filter(_inc_cnt__gt=0, _has_user_pos=0)
    if context.exclude_tags:
        # Exclude only when a positive (non-negative) tag application exists
        context.beatmaps = context.beatmaps.annotate(ta_pos=FilteredRelation('tagapplication', condition=Q(tagapplication__true_negative=False)))
        context.beatmaps = context.beatmaps.exclude(ta_pos__tag__name__in=context.exclude_tags)
    if context.metadata_phrases:
        for phrase in context.metadata_phrases:
            phrase_q = build_phrase_q(phrase)
            if phrase_q:
                context.include_q &= phrase_q
    # Return required tags so they can be included in weighting calculations
    return context.beatmaps, context.include_tag_names, context.required_tags, getattr(context, 'pp_calc_params', {})
