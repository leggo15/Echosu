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

    # Collect generic PP constraints so we can apply them as a single OR of ANDs
    # Example: pp>=800 pp<=850 ->
    #   (pp_nomod>=800 & pp_nomod<=850) |
    #   (pp_hd>=800 & pp_hd<=850) | ...
    pp_constraints = []  # list of tuples (lookup, value)
    
    # Store Acc and Miss parameters for PP calculation
    context.pp_calc_params = {}

    for term in search_terms:
        t = (term or '').strip()
        # Accept common "reversed" comparison operators typed by users:
        # - DT=>450  -> DT>=450
        # - DT=<550  -> DT<=550
        # Keep this normalization early so all downstream handlers see a canonical form.
        if '=>' in t or '=< ' in t or '=<'.strip() in t:
            # Note: no whitespace is expected inside tokens, but keep the replacement simple/safe.
            t = t.replace('=>', '>=').replace('=<', '<=')
        
        # Detect Acc and Miss parameters for PP calculation
        acc_match = re.match(r'^\s*acc=(\d+(?:\.\d+)?)\s*$', t, re.IGNORECASE)
        if acc_match:
            try:
                context.pp_calc_params['accuracy'] = float(acc_match.group(1))
                continue  # don't pass this term down further
            except ValueError:
                continue
                
        miss_match = re.match(r'^\s*miss=(\d+)\s*$', t, re.IGNORECASE)
        if miss_match:
            try:
                context.pp_calc_params['misses'] = int(miss_match.group(1))
                continue  # don't pass this term down further
            except ValueError:
                continue
        
        # Detect generic PP constraints (case-insensitive)
        m = re.match(r'^\s*pp(>=|<=|>|<|=)(\d+(?:\.\d+)?)\s*$', t, re.IGNORECASE)
        if m:
            op, val = m.group(1), m.group(2)
            try:
                num = float(val)
            except ValueError:
                continue
            # Map '=' to 'exact' so we can build filter keys without suffix
            lookup = {
                '>': 'gt', '<': 'lt', '>=': 'gte', '<=': 'lte', '=': 'exact'
            }.get(op)
            if lookup:
                pp_constraints.append((lookup, num))
            continue  # don't pass this term down further

        # Fallback to existing handlers
        if '=' in t and not any(op in t for op in ['>=', '<=', '>', '<']):
            context.beatmaps = handle_attribute_equal_query(context.beatmaps, t)
        elif any(op in t for op in ['>=', '<=', '>', '<']):
            context.beatmaps = handle_attribute_comparison_query(context.beatmaps, t)
        else:
            remaining_terms.append(t)

    # Apply accumulated generic PP constraints, if any
    if pp_constraints:
        pp_fields = ['pp_nomod', 'pp_hd', 'pp_hr', 'pp_dt', 'pp_ht', 'pp_ez', 'pp_fl']
        q_or = None
        for field in pp_fields:
            filters = {}
            for lookup, num in pp_constraints:
                if lookup == 'exact':
                    filters[field] = num
                else:
                    filters[f'{field}__{lookup}'] = num
            if filters:
                part = Q(**filters)
                q_or = part if q_or is None else (q_or | part)
        if q_or is not None:
            context.beatmaps = context.beatmaps.filter(q_or)

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
            matching_tags = Tag.objects.filter(name__iexact=cleaned)
            if matching_tags.exists():
                context.include_tags.update(tag.name for tag in matching_tags)
            else:
                context.metadata_phrases.append(cleaned)
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
                # Treat required non-tag terms as required general inclusion across fields
                context.include_q &= build_inclusion_q(required_term)
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

def build_phrase_q(phrase):
    cleaned = re.sub(r'\s+', ' ', (phrase or '').strip('"').strip())  # normalize spacing
    if not cleaned:
        return Q()
    return Q(
        Q(title__icontains=cleaned) |
        Q(version__icontains=cleaned) |
        Q(artist__icontains=cleaned) |
        Q(creator__icontains=cleaned) |
        Q(original_creator__icontains=cleaned) |
        Q(listed_owner__icontains=cleaned)
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
        'HP': 'drain',
        'DRAIN': 'drain',
        'LENGTH': 'total_length',
        'COUNT': 'playcount',
        'FAV': 'favourite_count',
        # Generic PP (special-cased below to search across all modded variants)
        'PP': 'pp',
        # Modded PP aliases
        'NM': 'pp_nomod',
        'HD': 'pp_hd',
        'HR': 'pp_hr',
        'DT': 'pp_dt',
        'HT': 'pp_ht',
        'EZ': 'pp_ez',
        'FL': 'pp_fl',
        'YEAR': 'last_updated__year',
    }

    field_name = field_map.get(attribute)
    if attribute == 'PP':
        # Equality for floats is uncommon; still support
        try:
            numeric_value = float(value)
        except ValueError:
            return beatmaps
        pp_fields = ['pp_nomod', 'pp_hd', 'pp_hr', 'pp_dt', 'pp_ht', 'pp_ez', 'pp_fl']
        q = None
        for f in pp_fields:
            part = Q(**{f: numeric_value})
            q = part if q is None else (q | part)
        if q is not None:
            beatmaps = beatmaps.filter(q)
        return beatmaps

    if field_name:
        try:
            if field_name in ['playcount', 'favourite_count']:
                numeric_value = int(value)
            elif field_name.endswith('__year'):
                numeric_value = int(value)
            else:
                numeric_value = float(value)
            filter_key = f'{field_name}'
            beatmaps = beatmaps.filter(**{filter_key: numeric_value})
        except ValueError:
            pass  # Handle invalid conversion
    return beatmaps

#----------#

def handle_attribute_comparison_query(beatmaps, term):
    # Normalize common "reversed" operator variants first (DT=>450, DT=<550, etc.)
    if '=>' in (term or '') or '=<'.strip() in (term or ''):
        term = (term or '').replace('=>', '>=').replace('=<', '<=')

    match = re.match(r'(AR|CS|BPM|OD|HP|DRAIN|LENGTH|COUNT|FAV|PP|NM|HD|HR|DT|HT|EZ|FL|YEAR)(>=|<=|>|<)(\d+(\.\d+)?)', term, re.IGNORECASE)
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
            'HP': 'drain',
            'DRAIN': 'drain',
            'LENGTH': 'total_length',
            'COUNT': 'playcount',
            'FAV': 'favourite_count',
            # Generic PP handled specially below
            'PP': 'pp',
            # Modded PP fields
            'NM': 'pp_nomod',
            'HD': 'pp_hd',
            'HR': 'pp_hr',
            'DT': 'pp_dt',
            'HT': 'pp_ht',
            'EZ': 'pp_ez',
            'FL': 'pp_fl',
            'YEAR': 'last_updated__year',
        }
        field_name = field_map.get(attribute)
        if lookup and attribute == 'PP':
            # Compare across all PP variants
            try:
                numeric_value = float(value)
            except ValueError:
                return beatmaps
            pp_fields = ['pp_nomod', 'pp_hd', 'pp_hr', 'pp_dt', 'pp_ht', 'pp_ez', 'pp_fl']
            q = None
            for f in pp_fields:
                filter_key = f"{f}__{lookup}"
                part = Q(**{filter_key: numeric_value})
                q = part if q is None else (q | part)
            if q is not None:
                beatmaps = beatmaps.filter(q)
            return beatmaps

        if lookup and field_name:
            try:
                if field_name in ['playcount', 'favourite_count']:
                    numeric_value = int(value)
                elif field_name.endswith('__year'):
                    numeric_value = int(value)
                else:
                    numeric_value = float(value)
                filter_key = f'{field_name}__{lookup}'
                beatmaps = beatmaps.filter(**{filter_key: numeric_value})
            except ValueError:
                pass  # Handle invalid numeric conversion
    return beatmaps
