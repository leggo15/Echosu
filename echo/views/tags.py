# echosu/views/tags.py
'''Tag CRUD, voting, and search endpoints.

Import order was cleaned earlier; this revision converts the remaining
string literals to single quotes wherever practical. Logic is unchanged.
'''

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import re
import unicodedata
import difflib

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
from better_profanity import profanity

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction, IntegrityError
from django.db.models import Count
from django.http import (
    JsonResponse,
    HttpResponseForbidden,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from ossapi.enums import UserLookupKey
from collections import defaultdict

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, Tag, TagApplication, Vote
from .auth import api
from ..templatetags.custom_tags import has_tag_edit_permission


# ----------------------------- Tag Views ----------------------------- #

def get_tags(request):
    '''Retrieve tags for a specific beatmap.'''
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)
    # Default to including predicted unless explicitly disabled
    _ip = request.GET.get('include_predicted')
    include_predicted = False if (_ip is not None and str(_ip).lower() in ['0', 'false', 'off']) else True

    # Fetch all tag applications for this beatmap with optimized queries
    applications = list(
        TagApplication.objects
        .filter(beatmap=beatmap, true_negative=False)
        .select_related('tag', 'tag__description_author')
        .only('user_id', 'tag__id', 'tag__name', 'tag__description', 'tag__description_author__username')
    )

    # Build structures in a single pass: user-applied counts, predictions, and description data
    user_counts = {}
    has_prediction = {}
    user_tag_names = set()
    # Prefer user-authored description when available; else fall back to any description
    desc_by_name_user = {}
    desc_by_name_pred = {}

    current_user_id = getattr(user, 'id', None)
    for app in applications:
        tag_name = app.tag.name
        # Cache descriptions to avoid O(N^2) lookups later
        if app.tag.description:
            author_name = getattr(app.tag.description_author, 'username', '') if app.tag.description_author else ''
            if app.user_id:
                # Prefer description data from any user-applied instance
                if tag_name not in desc_by_name_user:
                    desc_by_name_user[tag_name] = (app.tag.description, author_name)
            else:
                if tag_name not in desc_by_name_pred:
                    desc_by_name_pred[tag_name] = (app.tag.description, author_name)

        if app.user_id:
            user_counts[tag_name] = user_counts.get(tag_name, 0) + 1
            if current_user_id and app.user_id == current_user_id:
                user_tag_names.add(tag_name)
        else:
            # user is null → predicted
            has_prediction[tag_name] = True

    # Construct response: include predicted-only tags as orange unless any user has applied
    tags = []
    
    # Add user-applied tags (prefer description from user-applied entries when available)
    for tag_name, count in user_counts.items():
        desc, author = desc_by_name_user.get(tag_name) or desc_by_name_pred.get(tag_name) or ('', '')
        tags.append({
            'name': tag_name,
            'is_applied_by_user': tag_name in user_tag_names,
            'is_predicted': False,
            'apply_count': count,
            'description': desc,
            'description_author': author,
        })
    
    # Add predicted tags if enabled
    if include_predicted:
        for tag_name in has_prediction:
            if tag_name not in user_counts:  # Only add if no user has applied
                desc, author = desc_by_name_pred.get(tag_name) or ('', '')
                tags.append({
                    'name': tag_name,
                    'is_applied_by_user': False,
                    'is_predicted': True,
                    'apply_count': 0,
                    'description': desc,
                    'description_author': author,
                })
    
    # Optionally include true negatives for admin views when requested
    include_neg = str(request.GET.get('include_true_negatives', '0')).lower() in ['1', 'true', 'yes', 'on']
    if include_neg and getattr(user, 'is_staff', False):
        neg_apps = (
            TagApplication.objects
            .filter(beatmap=beatmap, true_negative=True)
            .select_related('tag')
            .only('tag__name')
        )
        neg_names = set()
        for app in neg_apps:
            tname = getattr(app.tag, 'name', '')
            if tname and tname not in neg_names:
                neg_names.add(tname)
                tags.append({
                    'name': tname,
                    'is_applied_by_user': False,
                    'is_predicted': False,
                    'apply_count': 0,
                    'description': '',
                    'description_author': '',
                    'true_negative': True,
                })

    # Sort by apply count (descending), then by name
    tags.sort(key=lambda x: (-x['apply_count'], x['name']))
    
    return JsonResponse(tags, safe=False)


def search_tags(request):
    '''Search for tags based on a query.'''
    search_query = request.GET.get('q', '')
    tags = (
        Tag.objects
        .filter(name__icontains=search_query)
        .annotate(beatmap_count=Count('beatmaps'))
        .values('name', 'beatmap_count')
        .order_by('-beatmap_count')
    )
    return JsonResponse(list(tags), safe=False)


def get_tags_bulk(request):
    '''Retrieve tags for multiple beatmaps in one request to eliminate N+1 queries.'''
    beatmap_ids = request.GET.getlist('beatmap_ids[]')
    user = request.user
    
    if not beatmap_ids:
        return JsonResponse({'tags': {}})
    
    # Default to including predicted unless explicitly disabled
    _ip = request.GET.get('include_predicted')
    include_predicted = False if (_ip is not None and str(_ip).lower() in ['0', 'false', 'off']) else True
    
    # Single query for all tag applications with related data
    tag_apps = list(
        TagApplication.objects
        .filter(beatmap__beatmap_id__in=beatmap_ids, true_negative=False)
        .select_related('beatmap', 'tag', 'tag__description_author')
        .only('beatmap__beatmap_id', 'user_id', 'tag__id', 'tag__name', 'tag__description', 'tag__description_author__username')
    )
    
    # Single query for user's tags across all beatmaps (if authenticated)
    user_tags = set()
    if user.is_authenticated:
        user_tags = set(
            TagApplication.objects
            .filter(user=user, beatmap__beatmap_id__in=beatmap_ids)
            .values_list('beatmap__beatmap_id', 'tag__name')
        )
    
    # Build response structure efficiently
    result = {bm_id: [] for bm_id in beatmap_ids}
    
    # Process tag applications and build tag data using counters instead of lists
    tag_data = defaultdict(lambda: defaultdict(lambda: {
        'name': '', 'is_applied_by_user': False, 'is_predicted': False,
        'apply_count': 0, 'description': '', 'description_author': ''
    }))
    for app in tag_apps:
        bm_id = app.beatmap.beatmap_id
        tag_name = app.tag.name
        entry = tag_data[bm_id][tag_name]
        if not entry['name']:
            entry['name'] = tag_name
        # Cache description data once
        if not entry['description'] and app.tag.description:
            entry['description'] = app.tag.description
            entry['description_author'] = getattr(app.tag.description_author, 'username', '') if app.tag.description_author else ''
        if app.user_id:
            entry['apply_count'] += 1
            # Mark as applied by current user if applicable
            if (bm_id, tag_name) in user_tags:
                entry['is_applied_by_user'] = True
        elif include_predicted:
            # Keep predicted flag; count predicted as 1 for display parity with previous behavior
            entry['is_predicted'] = True
            if entry['apply_count'] == 0:
                entry['apply_count'] = 1

    # Optionally include negatives (admin view helper)
    include_neg = str(request.GET.get('include_true_negatives', '0')).lower() in ['1', 'true', 'yes', 'on']
    if include_neg and getattr(user, 'is_staff', False):
        neg_qs = (
            TagApplication.objects
            .filter(beatmap__beatmap_id__in=beatmap_ids, true_negative=True)
            .select_related('beatmap', 'tag')
            .only('beatmap__beatmap_id', 'tag__name')
        )
        for app in neg_qs:
            bm_id = getattr(app.beatmap, 'beatmap_id', None)
            tag_name = getattr(app.tag, 'name', '')
            if bm_id and tag_name:
                entry = tag_data[bm_id][tag_name]
                # Mark as negative; do not inflate counts
                entry['name'] = entry['name'] or tag_name
                entry['true_negative'] = True

    # Finalize per-beatmap lists
    for bm_id, tags_for_bm in tag_data.items():
        final_tags = sorted(tags_for_bm.values(), key=lambda x: (-x['apply_count'], x['name']))
        result[bm_id] = final_tags
    
    return JsonResponse({'tags': result})
# ----------------------------- Ownership editing ----------------------------- #

@login_required
@require_POST
def edit_ownership(request):
    """Allow set owner or listed owner to change the displayed ownership.

    - If current user is the set owner (`original_creator`), they can assign `listed_owner` to any username (string).
    - If current user is the listed owner (`listed_owner`), they can set it back to the set owner only.
    """
    beatmap_id = request.POST.get('beatmap_id')
    new_owner = (request.POST.get('new_owner') or '').strip()

    if not beatmap_id:
        return JsonResponse({'status': 'error', 'message': 'Missing beatmap_id'}, status=400)

    bm = get_object_or_404(Beatmap, beatmap_id=beatmap_id)
    set_owner_name = (bm.original_creator or '').strip()
    set_owner_id = (bm.original_creator_id or '').strip()
    listed_owner_name = (bm.listed_owner or bm.creator or '').strip()
    listed_owner_id = (bm.listed_owner_id or '').strip()

    current_username = (request.user.username or '').strip()
    current_username_l = current_username.lower()
    current_osu_id = str(request.session.get('osu_id') or '')

    is_set_owner = (current_username_l == set_owner_name.lower()) or (current_osu_id and current_osu_id == set_owner_id)
    # Support multi-listed owners stored as comma-separated names/ids
    def _split_csv(val: str):
        return [x.strip() for x in (val or '').split(',') if x and x.strip()]
    listed_names = [x.lower() for x in _split_csv(listed_owner_name)] if ',' in listed_owner_name else [listed_owner_name.lower()] if listed_owner_name else []
    listed_ids = _split_csv(listed_owner_id)
    is_listed_owner = (current_username_l in listed_names) or (current_osu_id and current_osu_id in listed_ids)

    def resolve_user_by_input(raw: str):
        raw = (raw or '').strip()
        if not raw:
            return None, None
        # Accept id or username
        try:
            if raw.isdigit():
                u = api.user(int(raw), key=UserLookupKey.ID)
                return str(u.username), str(u.id)
            else:
                u = api.user(raw, key=UserLookupKey.USERNAME)
                return str(u.username), str(u.id)
        except Exception:
            # Fallback: keep input as name if not found
            return raw, None

    def parse_multi_owner_input(raw: str):
        """Parse input that may be a brace/comma list like "{1, 2}" or "name1, name2".
        Returns (names_list, ids_list) preserving order and removing duplicates.
        """
        text = (raw or '').strip()
        if not text:
            return [], []
        # Strip enclosing braces if present
        if text.startswith('{') and text.endswith('}'):
            text = text[1:-1]
        tokens = [t.strip() for t in text.split(',') if t.strip()] if (',' in text) else [text]
        seen_ids = set()
        seen_names = set()
        names_out, ids_out = [], []
        for tok in tokens:
            name, oid = resolve_user_by_input(tok)
            # Normalise
            name_key = (name or '').lower().strip()
            if oid:
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)
            if name_key:
                if name_key in seen_names and not oid:
                    continue
                seen_names.add(name_key)
            if name:
                names_out.append(name)
            if oid:
                ids_out.append(oid)
        return names_out, ids_out

    # Set owner has full control
    if is_set_owner:
        if not new_owner:
            return JsonResponse({'status': 'error', 'message': 'New owner required.'}, status=400)
        names, ids = parse_multi_owner_input(new_owner)
        if not names:
            return JsonResponse({'status': 'error', 'message': 'Invalid owner input.'}, status=400)
        bm.listed_owner = ', '.join(names)
        bm.listed_owner_id = ','.join(ids) if ids else ''
        bm.creator = bm.listed_owner
        # Mark owner-edited to lock out admin edits later and block refresh overwrite
        bm.listed_owner_is_manual_override = True
        bm.listed_owner_edited_by_owner = True
        bm.save(update_fields=['listed_owner', 'listed_owner_id', 'creator', 'listed_owner_is_manual_override', 'listed_owner_edited_by_owner'])
        return JsonResponse({'status': 'success', 'listed_owner': bm.listed_owner, 'listed_owner_id': bm.listed_owner_id})

    # Admins may edit only if set owner hasn't edited yet
    if request.user.is_staff and not bm.listed_owner_edited_by_owner:
        if not new_owner:
            return JsonResponse({'status': 'error', 'message': 'New owner required.'}, status=400)
        names, ids = parse_multi_owner_input(new_owner)
        if not names:
            return JsonResponse({'status': 'error', 'message': 'Invalid owner input.'}, status=400)
        bm.listed_owner = ', '.join(names)
        bm.listed_owner_id = ','.join(ids) if ids else ''
        bm.creator = bm.listed_owner
        bm.listed_owner_is_manual_override = True
        bm.save(update_fields=['listed_owner', 'listed_owner_id', 'creator', 'listed_owner_is_manual_override'])
        return JsonResponse({'status': 'success', 'listed_owner': bm.listed_owner, 'listed_owner_id': bm.listed_owner_id})

    # Listed owner can only hand ownership back to set owner
    if is_listed_owner:
        # Accept either set owner name or id
        desired = (new_owner or '').strip()
        if not desired:
            return JsonResponse({'status': 'error', 'message': 'Owner input required.'}, status=400)
        if not ((desired.isdigit() and desired == set_owner_id) or (desired.lower() == set_owner_name.lower())):
            return JsonResponse({'status': 'forbidden', 'message': 'Listed owner can only hand back to set owner.'}, status=403)
        bm.listed_owner = set_owner_name
        bm.listed_owner_id = set_owner_id
        bm.creator = set_owner_name
        # Handing back is also a manual action by listed owner; do not flag owner-edited
        bm.listed_owner_is_manual_override = True
        bm.save(update_fields=['listed_owner', 'listed_owner_id', 'creator', 'listed_owner_is_manual_override'])
        return JsonResponse({'status': 'success', 'listed_owner': bm.listed_owner, 'listed_owner_id': bm.listed_owner_id})

    return JsonResponse({'status': 'forbidden', 'message': 'Insufficient permissions'}, status=403)



# ----------------------------- Tag helpers ----------------------------- #

ALLOWED_TAG_PATTERN = re.compile(r'^[A-Za-z0-9 _\-/]{1,25}$')


def sanitize_tag(tag: str) -> str:
    '''Clean and normalise an incoming tag string before storage.''' 
    # Step 1: Trim leading and trailing spaces
    tag = tag.strip()

    # Step 2: Collapse multiple consecutive spaces into one
    tag = ' '.join(tag.split())

    # Step 3: Reduce consecutive identical characters to two
    tag = re.sub(r'(.)\1{2,}', r'\1\1', tag)

    # Step 4: Unicode normalization to NFC form
    tag = unicodedata.normalize('NFC', tag)

    # Step 5: Remove non-printable and control characters
    tag = re.sub(r'[^\x20-\x7E]', '', tag)

    # Step 6: Prevent leading or trailing non-alphanumeric characters
    tag = re.sub(r'^[^A-Za-z0-9]+', '', tag)  # leading
    tag = re.sub(r'[^A-Za-z0-9]+$', '', tag)  # trailing

    # Limit to a maximum of 3 words
    words = tag.split()
    if len(words) > 3:
        tag = ' '.join(words[:3])

    return tag


@login_required
def modify_tag(request):
    '''Apply or remove a tag for a beatmap by the current user.'''
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

    tag_name = request.POST.get('tag', '')
    beatmap_id = request.POST.get('beatmap_id')
    user = request.user
    # Optional: admin-only negative toggle
    negative_flag_raw = request.POST.get('true_negative')
    want_true_negative = str(negative_flag_raw).lower() in ['1', 'true', 'yes', 'on']
    if want_true_negative and not getattr(user, 'is_staff', False):
        return JsonResponse({'status': 'forbidden', 'message': 'Admin only action.'}, status=403)

    processed_tag = sanitize_tag(tag_name.lower())

    if not ALLOWED_TAG_PATTERN.match(processed_tag):
        msg = (
            'Tag must be 1-25 characters long and can only contain letters, numbers, '
            'spaces, hyphens, and underscores.'
        )
        return JsonResponse({'status': 'error', 'message': msg}, status=400)

    if profanity.contains_profanity(processed_tag):
        return JsonResponse({'status': 'error', 'message': 'Tag contains inappropriate language.'}, status=400)

    try:
        with transaction.atomic():
            tag, _ = Tag.objects.get_or_create(name=processed_tag)
            beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

            tag_application, created = TagApplication.objects.get_or_create(
                tag=tag,
                beatmap=beatmap,
                user=user,
                true_negative=True if want_true_negative else False,
            )

            if not created:
                tag_application.delete()
                if not TagApplication.objects.filter(tag=tag).exists():
                    tag.delete()
                return JsonResponse({'status': 'success', 'action': 'removed', 'true_negative': want_true_negative})

            return JsonResponse({'status': 'success', 'action': 'applied', 'true_negative': want_true_negative})

    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)


# ----------------------------- Description editing ----------------------------- #

def count_word_differences(old_desc: str, new_desc: str) -> int:
    old_words = old_desc.lower().split()
    new_words = new_desc.lower().split()
    diff = difflib.ndiff(old_words, new_words)
    return sum(1 for word in diff if word.startswith('- ') or word.startswith('+ '))


def sanitize_description(description: str) -> str:
    '''Normalise a tag description prior to validation.''' 
    description = description.strip()
    description = ' '.join(description.split())
    description = re.sub(r'(.)\1{2,}', r'\1\1', description)
    description = unicodedata.normalize('NFC', description)
    description = re.sub(r'[^\x20-\x7E]', '', description)
    description = re.sub(r'^[^A-Za-z0-9]+', '', description)
    return description

ALLOWED_DESCRIPTION_PATTERN = re.compile(r'^[A-Za-z0-9 .,!?\-_/\'"\"]{1,255}$')


@login_required
def edit_tags(request):
    '''Edit tag descriptions (GET shows form, POST handles AJAX).'''
    user = request.user
    if not has_tag_edit_permission(user):
        return HttpResponseForbidden('You do not have permission to edit tags.')

    if request.method == 'POST':
        if request.headers.get('x-requested-with') != 'XMLHttpRequest':
            return HttpResponseBadRequest('Invalid request method.')

        tag_id = request.POST.get('tag_id')
        new_description = request.POST.get('description', '').strip()
        if not tag_id or not new_description:
            return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

        processed_description = sanitize_description(new_description)
        if len(processed_description) == 0:
            return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
        if len(processed_description) > 100:
            return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)
        if not ALLOWED_DESCRIPTION_PATTERN.match(processed_description):
            msg = (
                'Description contains invalid characters. Allowed: letters, numbers, '
                'spaces, and basic punctuation (. , ! ? - _ / \' ").'
            )
            return JsonResponse({'status': 'error', 'message': msg}, status=400)
        if profanity.contains_profanity(processed_description):
            return JsonResponse({'status': 'error', 'message': 'Description contains inappropriate language.'}, status=400)

        tag = get_object_or_404(Tag, id=tag_id)
        if tag.is_locked:
            return JsonResponse({'status': 'error', 'message': 'This description is locked and cannot be edited.'}, status=403)
        old_description = tag.description
        word_diff_count = count_word_differences(old_description, processed_description)

        tag.description = processed_description
        if word_diff_count >= 3:
            tag.description_author = user
        # Save with user for history/audit
        tag.save(user=user)

        return JsonResponse({
            'status': 'success',
            'message': 'Tag description updated.',
            'word_diff_count': word_diff_count,
            'description_author': tag.description_author.username if tag.description_author else 'N/A',
            'upvotes': tag.upvotes,
            'downvotes': tag.downvotes,
        })

    # GET handling – search & paginate
    search_query = request.GET.get('search', '').strip()
    tags = (
        Tag.objects.filter(name__icontains=search_query) if search_query else Tag.objects.all()
    ).order_by('name')
    paginator = Paginator(tags, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'edit_tags.html', {'tags': page_obj, 'search_query': search_query})


@login_required
def vote_description(request):
    '''AJAX vote handler – supports toggling and switching votes.'''
    if request.method != 'POST' or request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    tag_id = request.POST.get('tag_id')
    vote_type = request.POST.get('vote_type')
    if not tag_id or vote_type not in ['upvote', 'downvote']:
        return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

    tag = get_object_or_404(Tag, id=tag_id)
    user = request.user

    try:
        existing_vote = Vote.objects.get(user=user, tag=tag)
        if existing_vote.vote_type == vote_type:
            existing_vote.delete()
            if vote_type == Vote.UPVOTE:
                tag.upvotes -= 1
            else:
                tag.downvotes -= 1
            vote_removed, vote_changed, new_vote = True, False, False
        else:
            if existing_vote.vote_type == Vote.UPVOTE:
                tag.upvotes -= 1
            else:
                tag.downvotes -= 1
            existing_vote.vote_type = vote_type
            existing_vote.save()
            if vote_type == Vote.UPVOTE:
                tag.upvotes += 1
            else:
                tag.downvotes += 1
            vote_removed, vote_changed, new_vote = False, True, False
    except Vote.DoesNotExist:
        Vote.objects.create(user=user, tag=tag, vote_type=vote_type)
        if vote_type == Vote.UPVOTE:
            tag.upvotes += 1
        else:
            tag.downvotes += 1
        vote_removed, vote_changed, new_vote = False, False, True

    tag.is_locked = (tag.upvotes - tag.downvotes) >= 10
    tag.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Vote recorded.' if new_vote or vote_changed else 'Vote removed.',
        'upvotes': tag.upvotes,
        'downvotes': tag.downvotes,
        'is_locked': tag.is_locked,
        'tag_name': tag.name,
        'removed': vote_removed,
        'changed': vote_changed,
        'new_vote': new_vote,
        'current_vote': vote_type if new_vote or vote_changed else None,
    })


@login_required
def update_tag_description(request):
    '''Lightweight endpoint used elsewhere; left unchanged but unifies quote style.'''
    if request.method != 'POST' or request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

    tag_id = request.POST.get('tag_id')
    new_description = request.POST.get('description', '').strip()
    user = request.user

    if not has_tag_edit_permission(user):
        return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

    tag = get_object_or_404(Tag, id=tag_id)
    if tag.is_locked:
        return JsonResponse({'status': 'error', 'message': 'This description is locked and cannot be edited.'}, status=403)

    processed_description = sanitize_description(new_description)
    if len(processed_description) == 0:
        return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
    if len(processed_description) > 100:
        return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)
    if not ALLOWED_DESCRIPTION_PATTERN.match(processed_description):
        msg = (
            'Description contains invalid characters. Allowed: letters, numbers, '
            'spaces, and basic punctuation (. , ! ? - _ / \' ").'
        )
        return JsonResponse({'status': 'error', 'message': msg}, status=400)
    if profanity.contains_profanity(processed_description):
        return JsonResponse({'status': 'error', 'message': 'Tag contains inappropriate language.'}, status=400)

    # Optional: update author only on meaningful change
    word_diff_count = count_word_differences(tag.description, processed_description)

    try:
        with transaction.atomic():
            tag.description = processed_description
            if word_diff_count >= 3:
                tag.description_author = user
            tag.save(user=user)
        return JsonResponse({'status': 'success', 'message': 'Description updated successfully.'})
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)
