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
import shlex
from collections import defaultdict

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
from nltk.stem import PorterStemmer

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib.auth.models import User  # noqa: F401  (used indirectly)
from django.core.paginator import Paginator
from django.db.models import (
    Q,
    Count,
    F,
    Value,
    IntegerField,
    Subquery,
    OuterRef,
)
from django.shortcuts import render

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, Tag, TagApplication
from ..operators import (
    handle_quotes,
    handle_exclusion,
    handle_inclusion,
    handle_attribute_queries,
    handle_general_inclusion,
)
from ..utils import QueryContext

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

    def annotate_and_order_beatmaps(qs, include_tags, exact_tags, sort):
        qs = qs.filter(tags__name__in=include_tags).distinct()
        total_sub = (
            Beatmap.objects.filter(pk=OuterRef('pk'))
            .annotate(real_count=Count('tags'))
            .values('real_count')[:1]
        )
        if sort == 'tag_weight':
            qs = (
                qs.annotate(
                    tag_match_count=Count('tags', filter=Q(tags__name__in=include_tags), distinct=True),
                    exact_match_total_count=Count('tags', filter=Q(tags__name__in=exact_tags)),
                    exact_match_distinct_count=Count('tags', filter=Q(tags__name__in=exact_tags), distinct=True),
                    total_tag_count=Subquery(total_sub),
                )
                .annotate(
                    tag_miss_match_count=Value(len(include_tags), output_field=IntegerField()) - F('tag_match_count'),
                    tag_surplus_count=F('total_tag_count') - F('tag_match_count'),
                    tag_weight=(
                        (F('exact_match_distinct_count') * 5.0 +
                         F('exact_match_total_count') * 1.0 +
                         F('tag_match_count') * 0.1) /
                        (F('tag_miss_match_count') * 1 + (F('tag_surplus_count') * 3))
                    ),
                )
                .order_by('-tag_weight')
            )
        else:
            qs = qs.order_by('-favourite_count', '-playcount')
        return qs

    # -------------------------------------------------------------
    # Query parameter handling begins here.
    # -------------------------------------------------------------
    query = request.GET.get('query', '').strip()
    selected_mode = request.GET.get('mode', 'osu').strip().lower()
    star_min = request.GET.get('star_min', '0').strip()
    star_max = request.GET.get('star_max', '15').strip()
    sort = request.GET.get('sort', '')

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
            star_max = 15.0
    except ValueError:
        star_max = 15.0

    MODE_MAPPING = {'osu': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
    mapped_mode = MODE_MAPPING.get(selected_mode, 'osu')

    beatmaps = Beatmap.objects.filter(mode__iexact=mapped_mode)
    beatmaps = beatmaps.filter(difficulty_rating__gte=star_min)
    if star_max < 15:
        beatmaps = beatmaps.filter(difficulty_rating__lte=star_max)

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
    beatmaps, include_tags = build_query_conditions(beatmaps, [t[0] for t in parsed_terms])

    stemmed_terms = process_search_terms(parsed_terms)
    exact_tags = identify_exact_match_tags(include_tags, stemmed_terms)

    if sort not in ['tag_weight', 'popularity']:
        sort = 'tag_weight' if query else 'popularity'

    if include_tags:
        beatmaps = annotate_and_order_beatmaps(beatmaps, include_tags, exact_tags, sort)
    else:
        beatmaps = beatmaps.annotate(
            total_tag_apply_count=Count('tagapplication'),
            tag_weight=F('total_tag_apply_count'),
            popularity=F('favourite_count') * 0.5 + F('playcount') * 0.001,
        )
        beatmaps = beatmaps.order_by('-' + sort) if sort in ['tag_weight', 'popularity'] else beatmaps.order_by('-favourite_count', '-playcount')

    paginator = Paginator(beatmaps, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    annotate_search_results_with_tags(page_obj.object_list, request.user)

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
        },
    )

# ---------------------------------------------------------------------------
# Helper utilities (mostly unchanged, but quote style unified)
# ---------------------------------------------------------------------------

def annotate_search_results_with_tags(beatmaps, user):
    beatmap_ids = beatmaps.values_list('id', flat=True)
    tag_apps = TagApplication.objects.filter(beatmap_id__in=beatmap_ids).select_related('tag')
    beatmap_tag_counts = defaultdict(lambda: defaultdict(int))
    user_applied_tags = defaultdict(set)

    for app in tag_apps:
        beatmap_tag_counts[app.beatmap_id][app.tag] += 1
        if user.is_authenticated and app.user_id == user.id:
            user_applied_tags[app.beatmap_id].add(app.tag)

    for bm in beatmaps:
        tags_counts = [
            {
                'tag': tag,
                'apply_count': cnt,
                'is_applied_by_user': tag in user_applied_tags.get(bm.id, set()),
            }
            for tag, cnt in beatmap_tag_counts.get(bm.id, {}).items()
        ]
        bm.tags_with_counts = sorted(tags_counts, key=lambda x: -x['apply_count'])
    return beatmaps


def parse_search_terms(query: str):
    '''Split query by whitespace, respecting quoted substrings.''' 
    return re.findall(r'[-.]?"[^"]+"|[-.]?[^"\s]+', query)


def build_query_conditions(beatmaps, search_terms):
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
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.include_tag_names).distinct()
    if context.exclude_tags:
        context.beatmaps = context.beatmaps.exclude(tags__name__in=context.exclude_tags)
    return context.beatmaps, context.include_tag_names
