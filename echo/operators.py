# operators.py

import re
from django.db.models import Q
from .models import Tag
from nltk.stem import PorterStemmer

stemmer = PorterStemmer()

def stem_word(word):
    return stemmer.stem(word)

#----------#

def handle_attribute_queries(context, search_terms):
    """
    Handles attribute equality and comparison queries.
    """
    remaining_terms = []
    for term in search_terms:
        term = term.strip()
        if '=' in term and not any(op in term for op in ['>=', '<=', '>', '<']):
            context.beatmaps = handle_attribute_equal_query(context.beatmaps, term)
        elif any(op in term for op in ['>=', '<=', '>', '<']):
            context.beatmaps = handle_attribute_comparison_query(context.beatmaps, term)
        else:
            remaining_terms.append(term)
    return remaining_terms

#----------#

def handle_quotes(context, search_terms):
    """
    Processes quoted terms as single tags.
    """
    processed_terms = []
    for term in search_terms:
        if re.match(r'^".+"$', term):
            cleaned = term.strip('"')
            context.include_tags.add(cleaned)
        else:
            processed_terms.append(term)
    return processed_terms

#----------#

def handle_exclusion(context, search_terms):
    """
    Processes exclusion terms starting with '-'.
    """
    processed_terms = []
    for term in search_terms:
        if term.startswith('-'):
            exclude_term = term.lstrip('-').strip('"').strip()
            matching_tags = Tag.objects.filter(name__icontains=exclude_term)
            if matching_tags.exists():
                context.exclude_tags.update(tag.name for tag in matching_tags)
            else:
                context.exclude_q |= build_exclusion_q(exclude_term)
        else:
            processed_terms.append(term)
    return processed_terms

#----------#

def handle_inclusion(context, search_terms):
    """
    Processes inclusion terms starting with '.'.
    """
    processed_terms = []
    for term in search_terms:
        if term.startswith('.'):
            required_term = term.lstrip('.').strip('"').strip()
            matching_tags = Tag.objects.filter(name__iexact=required_term)
            if matching_tags.exists():
                context.required_tags.update(tag.name for tag in matching_tags)
            else:
                # If required tag does not exist, no results should be returned
                context.beatmaps = context.beatmaps.none()
        else:
            processed_terms.append(term)
    return processed_terms

#----------#

def handle_general_inclusion(context, search_terms):
    """
    Processes general inclusion terms.
    """
    for term in search_terms:
        include_term = term.strip('"').strip()
        matching_tags = Tag.objects.filter(name__icontains=include_term)
        if matching_tags.exists():
            context.include_tag_names.update(tag.name for tag in matching_tags)
        else:
            context.include_q &= build_inclusion_q(include_term)

#----------#

def build_exclusion_q(term):
    # Handle exclusion terms
    return Q(
        Q(tags__name__iexact=term) |
        Q(genres__name__iexact=term) |
        Q(title__icontains=term) |
        Q(creator__icontains=term) |
        Q(artist__icontains=term) |
        Q(version__icontains=term)
    )

#----------#

def build_inclusion_q(term):
    # Handle inclusion terms
    return Q(
        Q(tags__name__iexact=term) |
        Q(genres__name__iexact=term) |
        Q(title__icontains=term) |
        Q(creator__icontains=term) |
        Q(artist__icontains=term) |
        Q(version__icontains=term) |
        Q(total_length__icontains=term) |
        Q(drain__icontains=term) |
        Q(accuracy__icontains=term) |
        Q(difficulty_rating__icontains=term)
    )

#----------#

def handle_attribute_equal_query(beatmaps, term):
    attribute, value = term.split('=', 1)
    attribute = attribute.upper().strip()
    value = value.strip()

    # Map attribute to db field name
    field_map = {
        'AR': 'ar',
        'CS': 'cs',
        'BPM': 'bpm',
        'OD': 'accuracy',
        'LENGTH': 'total_length',
        'COUNT': 'playcount',
        'FAV': 'favourite_count',
    }

    field_name = field_map.get(attribute)
    if field_name:
        try:
            if field_name in ['playcount', 'favourite_count']:
                numeric_value = float(value)
            else:
                numeric_value = float(value)
            filter_key = f'{field_name}'
            beatmaps = beatmaps.filter(**{filter_key: numeric_value})
        except ValueError:
            pass  # Handle invalid conversion
    return beatmaps

#----------#

def handle_attribute_comparison_query(beatmaps, term):
    match = re.match(r'(AR|CS|BPM|OD|LENGTH|COUNT|FAV)(>=|<=|>|<)(\d+(\.\d+)?)', term, re.IGNORECASE)
    if match:
        attribute, operator, value, _ = match.groups()
        attribute = attribute.upper().strip()
        lookup_map = {
            '>': 'gt',
            '<': 'lt',
            '>=': 'gte',
            '<=': 'lte',
        }
        lookup = lookup_map.get(operator)
        field_map = {
            'AR': 'ar',
            'CS': 'cs',
            'BPM': 'bpm',
            'OD': 'accuracy',
            'LENGTH': 'total_length',
            'COUNT': 'playcount',
            'FAV': 'favourite_count',
        }
        field_name = field_map.get(attribute)
        if lookup and field_name:
            try:
                if field_name in ['playcount', 'favourite_count']:
                    numeric_value = int(value)
                else:
                    numeric_value = float(value)
                filter_key = f'{field_name}__{lookup}'
                beatmaps = beatmaps.filter(**{filter_key: numeric_value})
            except ValueError:
                pass  # Handle invalid numeric conversion
    return beatmaps
