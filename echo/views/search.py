# echosu/views/search.py

# Standard library imports
import re
from collections import defaultdict
import shlex

# Third-party imports
from nltk.stem import PorterStemmer

# Django imports
from django.db.models import Q, Count, F, Value, IntegerField, Subquery, OuterRef
from django.core.paginator import Paginator
from django.shortcuts import render

# Local application imports
from ..models import Beatmap, TagApplication
# Assuming operators.py and utils.py are in the parent 'echosu' directory
from ..operators import handle_quotes, handle_exclusion, handle_inclusion, handle_attribute_queries, handle_general_inclusion
from ..utils import QueryContext



# ----------------------------- Search Views ----------------------------- #

from django.shortcuts import render
from django.db.models import Q, Count, Value, IntegerField
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from ..models import Beatmap, TagApplication, Tag
import re
from collections import defaultdict


def search_results(request):

    ############################################
    from nltk.stem import PorterStemmer
    from django.db.models import Count, Q, F
    import shlex

    # Initialize the stemmer
    stemmer = PorterStemmer()

    def stem_word(word):
        """Stems a single word."""
        return stemmer.stem(word.lower())

    def stem_phrase(phrase):
        """Stems each word in a multi-word phrase."""
        return ' '.join(stem_word(word) for word in phrase.split())

    def parse_query_with_quotes(raw_query):
        """
        Parses the raw search query and returns a list of tuples: Each tuple contains (term, is_quoted)
        Handles unmatched quotes by ignoring them.
        """
        lexer = shlex.shlex(raw_query, posix=True)
        lexer.whitespace_split = True
        lexer.quotes = '"\''
        tokens = []
        
        try:
            for token in lexer:
                is_quoted = ' ' in token
                tokens.append((token, is_quoted))
        except ValueError as e:
            # Handle the unmatched quotes by stripping them and re-parsing
            print(f"Warning: {e}. Attempting to parse without unmatched quotes.")
            # Remove all quotes and split the string
            fixed_query = raw_query.replace('"', '').replace("'", "")
            lexer = shlex.shlex(fixed_query, posix=True)
            lexer.whitespace_split = True
            lexer.quotes = ''  # Disable quoting
            for token in lexer:
                tokens.append((token, False))
        
        return tokens

    def process_search_terms(parsed_terms):
        """
        Processes parsed search terms by sanitizing and stemming.

        Args:
            parsed_terms (list of tuples): List of (term, is_quoted).

        Returns:
            set: Set of stemmed sanitized search terms.
        """
        stemmed_search_terms = set()
        for term, is_quoted in parsed_terms:
            # Sanitize the term by stripping quotes
            sanitized_term = term.strip('"\'')
            if ' ' in sanitized_term:
                # If multi-word, stem each word
                stemmed_term = stem_phrase(sanitized_term)
            else:
                # If single-word, stem directly
                stemmed_term = stem_word(sanitized_term)
            stemmed_search_terms.add(stemmed_term)
        return stemmed_search_terms

    def identify_exact_match_tags(include_tag_names, stemmed_search_terms):
        """
        Identifies exact match tag names based on stemmed search terms.

        Args:
            include_tag_names (set): Set of tag names to include.
            stemmed_search_terms (set): Set of stemmed search terms.

        Returns:
            set: Set of exact match tag names.
        """
        exact_match_tag_names = set()
        for tag in include_tag_names:
            sanitized_tag = tag.strip('"\'')
            if ' ' in sanitized_tag:
                # Stem each word in the tag
                stemmed_tag = stem_phrase(sanitized_tag)
            else:
                stemmed_tag = stem_word(sanitized_tag)
            if stemmed_tag in stemmed_search_terms:
                exact_match_tag_names.add(tag)
            else:
                # Additionally, check if any word in the tag matches
                for word in sanitized_tag.split():
                    if stem_word(word) in stemmed_search_terms:
                        exact_match_tag_names.add(tag)
                        break
        return exact_match_tag_names

    from django.db.models import Count, OuterRef, Subquery, F, Value, IntegerField, Q

    def annotate_and_order_beatmaps(beatmaps, include_tag_names, exact_match_tag_names, sort_method):
        beatmaps_filtered = beatmaps.filter(tags__name__in=include_tag_names).distinct()

        # Prepare subquery that grabs total tag count (no filter):
        total_tags_subquery = (
            Beatmap.objects
            .filter(pk=OuterRef('pk'))
            .annotate(real_count=Count('tags', distinct=False))
            .values('real_count')[:1]
        )

        if sort_method == 'tag_weight':
            annotated_beatmaps = (
                beatmaps_filtered
                .annotate(
                    tag_match_count=Count('tags', 
                    filter=Q(tags__name__in=include_tag_names), distinct=True),
                    exact_match_total_count=Count('tags', 
                    filter=Q(tags__name__in=exact_match_tag_names)),
                    exact_match_distinct_count=Count('tags', 
                    filter=Q(tags__name__in=exact_match_tag_names), distinct=True),
                    total_tag_count=Subquery(total_tags_subquery),
                )
                .annotate(
                    tag_miss_match_count=Value(len(include_tag_names), output_field=IntegerField()) - F('tag_match_count'),
                    tag_surplus_count=F('total_tag_count') - F('tag_match_count'),
                    tag_weight=(
                        (F('exact_match_distinct_count')*3.0 +
                        F('exact_match_total_count')*1.0 +
                        F('tag_match_count')*0.3)
                        / (F('tag_miss_match_count') * 0.5 + 1 + (F('tag_surplus_count') * 1.3))
                    )
                )
                .order_by('-tag_weight')
            )

        else:
            annotated_beatmaps = beatmaps_filtered.order_by('-favourite_count', '-playcount')

        return annotated_beatmaps



    ############################################


    # Start of the function
    query = request.GET.get('query', '').strip()
    print("Raw query string:", query)  # Debug

    selected_mode = request.GET.get('mode', 'osu').strip().lower()
    star_min = request.GET.get('star_min', '0').strip()
    star_max = request.GET.get('star_max', '15').strip()
    sort = request.GET.get('sort', '')

    # Get status filter values
    status_ranked = request.GET.get('status_ranked', False)
    status_loved = request.GET.get('status_loved', False)
    status_unranked = request.GET.get('status_unranked', False)

    # Validate and convert star ratings
    try:
        star_min = float(star_min)
        if star_min < 0:
            star_min = 0.0
    except ValueError:
        star_min = 0.0
    try:
        star_max = float(star_max)
        if star_max < star_min:
            star_max = 15.0
    except ValueError:
        star_max = 15.0

    MODE_MAPPING = {
        'osu': 'osu',
        'taiko': 'taiko',
        'catch': 'fruits',
        'mania': 'mania',
    }

    if selected_mode not in MODE_MAPPING:
        selected_mode = 'osu'  # Default to 'osu' mode if invalid

    beatmaps = Beatmap.objects.all()

    # Filter by mode
    mapped_mode = MODE_MAPPING[selected_mode]
    if mapped_mode:
        beatmaps = beatmaps.filter(mode__iexact=mapped_mode)
    else:
        beatmaps = beatmaps.filter(mode__iexact='osu')

    # Filter by star rating
    if star_max >= 15:
        beatmaps = beatmaps.filter(difficulty_rating__gte=star_min)
    else:
        beatmaps = beatmaps.filter(difficulty_rating__gte=star_min, difficulty_rating__lte=star_max)

    # Filter by status
    if status_ranked or status_loved or status_unranked:
        status_filters = Q()
        if status_ranked:
            status_filters |= Q(status='Ranked') | Q(status='Approved')
        if status_loved:
            status_filters |= Q(status='Loved')
        if status_unranked:
            status_filters |= (
                Q(status='Graveyard') | Q(status='WIP') | Q(status='Pending') | Q(status='Qualified')
            )
        beatmaps = beatmaps.filter(status_filters)

    # Process query
    # Replace the existing parse_search_terms with enhanced parsing
    parsed_terms = parse_query_with_quotes(query)
    print("Parsed search terms:", parsed_terms)  # Debug

    # Extract just the terms without the quoted status
    search_terms = [term for term, is_quoted in parsed_terms]
    print("Search terms:", search_terms)  # Debug

    # Build query conditions
    beatmaps, include_tag_names = build_query_conditions(beatmaps, search_terms)

    # Sanitize and stem the search terms
    stemmed_search_terms = process_search_terms(parsed_terms)

    # Identify exact match tag names based on stemming
    exact_match_tag_names = identify_exact_match_tags(include_tag_names, stemmed_search_terms)

    # Determine sort method
    if sort not in ['tag_weight', 'popularity']:
        if query:
            sort = 'tag_weight'
        else:
            sort = 'popularity'

    # Annotate beatmaps with tag_match_count, tag_apply_count, and weight
    if include_tag_names:
        print("include_tag_names:", include_tag_names)
        print("exact_match_tag_names:", exact_match_tag_names)

        # Annotate and order the queryset
        beatmaps = annotate_and_order_beatmaps(beatmaps, include_tag_names, exact_match_tag_names, sort)
    else:
        beatmaps = beatmaps.annotate(
            total_tag_apply_count=Count('tagapplication'),
            tag_weight=F('total_tag_apply_count'),  # Define weight
            popularity=F('favourite_count') * 0.5 + F('playcount') * 0.001,
        )
        # Apply sorting based on user preference
        if sort == 'tag_weight':
            beatmaps = beatmaps.order_by('-tag_weight')
        elif sort == 'popularity':
            beatmaps = beatmaps.order_by('-popularity')
        else:
            # Default sorting if sort parameter is invalid
            beatmaps = beatmaps.order_by('-favourite_count', '-playcount')

    # Pagination
    paginator = Paginator(beatmaps, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Annotate beatmaps with tag details
    annotate_search_results_with_tags(page_obj.object_list, request.user)

    context = {
        'beatmaps': page_obj,
        'query': query,
        'star_min': star_min,
        'star_max': star_max,
        'sort': sort,
        # Pass back the status filters to the template to remember the selection
        'status_ranked': status_ranked,
        'status_loved': status_loved,
        'status_unranked': status_unranked,
    }

    return render(request, 'search_results.html', context)

#######################################################################################

from collections import defaultdict

def annotate_search_results_with_tags(beatmaps, user):
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
        if user.is_authenticated and tag_app.user_id == user.id:
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

#######################################################################################

def parse_search_terms(query):
    """
    Use regular expression to split the query into terms, treating quoted strings as single terms.
    """
    return re.findall(r'[-.]?"[^"]+"|[-.]?[^"\s]+', query)

#######################################################################################

from ..operators import (
    handle_quotes,
    handle_exclusion,
    handle_inclusion,
    handle_attribute_queries,
    handle_general_inclusion
)
from ..utils import QueryContext

def build_query_conditions(beatmaps, search_terms):
    """
    Build inclusion, exclusion, and required tag conditions based on the search terms.
    """
    context = QueryContext(beatmaps)
    
    # Define the order of operations
    query_operations = [
        handle_attribute_queries,
        handle_quotes,
        handle_exclusion,
        handle_inclusion,
        handle_general_inclusion
    ]
    
    # Apply each operator function in order
    for operation in query_operations:
        search_terms = operation(context, search_terms)
        if context.beatmaps is None or not context.beatmaps.exists():
            break  # Early exit if no beatmaps match
    
    # Apply inclusion Q objects
    if context.include_q:
        context.beatmaps = context.beatmaps.filter(context.include_q)
    
    # Apply exclusion Q objects
    if context.exclude_q:
        context.beatmaps = context.beatmaps.exclude(context.exclude_q)
    
    # Apply required tags filter
    if context.required_tags:
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.required_tags)
    
    # Apply inclusion tags filter
    if context.include_tag_names:
        context.beatmaps = context.beatmaps.filter(tags__name__in=context.include_tag_names).distinct()
    
    # Apply exclusion tags filter
    if context.exclude_tags:
        context.beatmaps = context.beatmaps.exclude(tags__name__in=context.exclude_tags)
    
    return context.beatmaps, context.include_tag_names
