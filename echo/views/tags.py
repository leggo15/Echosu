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

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import Beatmap, Tag, TagApplication, Vote
from ..templatetags.custom_tags import has_tag_edit_permission


# ----------------------------- Tag Views ----------------------------- #

def get_tags(request):
    '''Retrieve tags for a specific beatmap.'''
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Fetch all tags for this beatmap with a count of distinct users that applied each tag
    tags_with_user_counts = (
        TagApplication.objects
        .filter(beatmap=beatmap)
        .values('tag__name', 'tag__description', 'tag__description_author__username')
        .annotate(apply_count=Count('user', distinct=True))
        .order_by('-apply_count')
    )

    if request.user.is_authenticated:
        # Fetch all TagApplication instances for the current user and this beatmap
        user_tag_names = set(
            TagApplication.objects
            .filter(user=user, beatmap=beatmap)
            .values_list('tag__name', flat=True)
        )
    else:
        user_tag_names = []

    # Construct the list of dictionaries
    tags_with_counts_list = [
        {
            'name': tag['tag__name'],
            'description': tag.get('tag__description', 'No description available.'),
            'description_author': tag.get('tag__description_author__username', ''),
            'apply_count': tag['apply_count'],
            'is_applied_by_user': tag['tag__name'] in user_tag_names,
        }
        for tag in tags_with_user_counts
    ]

    return JsonResponse(tags_with_counts_list, safe=False)


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
            )

            if not created:
                tag_application.delete()
                if not TagApplication.objects.filter(tag=tag).exists():
                    tag.delete()
                return JsonResponse({'status': 'success', 'action': 'removed'})

            return JsonResponse({'status': 'success', 'action': 'applied'})

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
        old_description = tag.description
        word_diff_count = count_word_differences(old_description, processed_description)

        tag.description = processed_description
        if word_diff_count >= 3:
            tag.description_author = user
        tag.save()

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
    if len(new_description) == 0:
        return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
    if len(new_description) > 100:
        return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)
    if not ALLOWED_DESCRIPTION_PATTERN.match(new_description):
        msg = (
            'Description contains invalid characters. Allowed: letters, numbers, '
            'spaces, and basic punctuation (. , ! ? - _ / \' ").'
        )
        return JsonResponse({'status': 'error', 'message': msg}, status=400)
    if profanity.contains_profanity(new_description):
        return JsonResponse({'status': 'error', 'message': 'Tag contains inappropriate language.'}, status=400)

    try:
        with transaction.atomic():
            tag.description = new_description
            tag.save()
        return JsonResponse({'status': 'success', 'message': 'Description updated successfully.'})
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)
