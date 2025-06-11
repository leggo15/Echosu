# echosu/views/tags.py

# Standard library imports
import re
import unicodedata
import difflib

# Third-party imports
from better_profanity import profanity

# Django imports
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator

# Local application imports
from ..models import Beatmap, Tag, TagApplication, Vote
from ..templatetags.custom_tags import has_tag_edit_permission # Assuming this is in yourapp/templatetags/


# ----------------------------- Tag Views ----------------------------- #


def get_tags(request):
    """
    Retrieve tags for a specific beatmap
    """
    beatmap_id = request.GET.get('beatmap_id')
    user = request.user
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # Fetch all tags for this beatmap with a count of distinct users that applied each tag
    tags_with_user_counts = TagApplication.objects.filter(
        beatmap=beatmap
    ).values('tag__name', 'tag__description', 'tag__description_author__username').annotate(
        apply_count=Count('user', distinct=True)
    ).order_by('-apply_count')

    if request.user.is_authenticated:
        # Fetch all TagApplication instances for the current user and this beatmap
        user_tag_names = set(TagApplication.objects.filter(
            user=user, beatmap=beatmap
        ).values_list('tag__name', flat=True))
    else:
        user_tag_names = []

    # Construct the list of dictionaries
    tags_with_counts_list = [
        {
            'name': tag['tag__name'],
            'description': tag.get('tag__description', 'No description abaliable.'),
            'description_author': tag.get('tag__description_author__username', ''),
            'apply_count': tag['apply_count'],
            'is_applied_by_user': tag['tag__name'] in user_tag_names
        } for tag in tags_with_user_counts
    ]

    return JsonResponse(tags_with_counts_list, safe=False)


def search_tags(request):
    """
    Search for tags based on a query.
    """
    search_query = request.GET.get('q', '')
    tags = Tag.objects.filter(name__icontains=search_query).annotate(
        beatmap_count=Count('beatmaps')
    ).values('name', 'beatmap_count').order_by('-beatmap_count')
    return JsonResponse(list(tags), safe=False)


from better_profanity import profanity
import unicodedata

def sanitize_tag(tag):
    """
    Sanitize the tag by performing the following steps:
    1. Trim leading and trailing spaces.
    2. Collapse multiple consecutive spaces into one.
    3. Reduce any character repeated more than twice consecutively to two.
    4. Normalize Unicode characters to NFC form.
    5. Remove non-printable and control characters.
    6. Prevent leading or trailing non-alphanumeric characters.
    """
    # Step 1: Trim leading and trailing spaces
    tag = tag.strip()
    
    # Step 2: Collapse multiple consecutive spaces into one
    tag = ' '.join(tag.split())
    
    # Step 3: Reduce consecutive identical characters to two
    tag = re.sub(r'(.)\1{2,}', r'\1\1', tag)
    
    # Step 4: Unicode normalization to NFC form
    tag = unicodedata.normalize('NFC', tag)
    
    # Step 5: Remove non-printable and control characters
    # This regex matches any character that is not a printable character or space
    tag = re.sub(r'[^\x20-\x7E]', '', tag)
    
    # Step 6: Prevent leading or trailing non-alphanumeric characters
    # Remove leading non-alphanumeric characters
    tag = re.sub(r'^[^A-Za-z0-9]+', '', tag)
    # Remove trailing non-alphanumeric characters
    tag = re.sub(r'[^A-Za-z0-9]+$', '', tag)

    # limit to a maximum of 3 words
    max_words = 3
    words = tag.split()
    if len(words) > max_words:
        tag = ' '.join(words[:max_words])
    
    # Define a set of reserved words. might use this later
    """
    reserved_words = {'admin', 'null', 'undefined'}
    if tag.lower() in reserved_words:
        tag += '_tag'
    """
    
    return tag

# Define the allowed tag pattern if not already defined
ALLOWED_TAG_PATTERN = re.compile(r'^[A-Za-z0-9 _\-\/]{1,25}$')

@login_required
def modify_tag(request):
    """
    Apply or remove a tag for a beatmap by the current user.
    Additionally, remove the tag from the database if it's no longer used.
    """
    if request.method == 'POST':
        tag_name = request.POST.get('tag', '')
        beatmap_id = request.POST.get('beatmap_id')
        user = request.user

        processed_tag = sanitize_tag(tag_name.lower())

        # Disallow specific chars and set max length
        if not ALLOWED_TAG_PATTERN.match(processed_tag):
            error_message = 'Tag must be 1-25 characters long and can only contain letters, numbers, spaces, hyphens, and underscores.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Profanity filtering
        if profanity.contains_profanity(processed_tag):
            error_message = 'Tag contains inappropriate language.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Wrap the following operations in an atomic transaction to ensure data integrity
        try:
            with transaction.atomic():
                # Create the tag if it doesn't exist
                tag, created_tag = Tag.objects.get_or_create(name=processed_tag)
                beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

                # Check if the tag application already exists
                tag_application, created = TagApplication.objects.get_or_create(
                    tag=tag,
                    beatmap=beatmap,
                    user=user
                )

                # If not created, it means the tag application already existed, so we remove it
                if not created:
                    tag_application.delete()

                    # After deletion, check if the tag has any remaining applications
                    remaining_applications = TagApplication.objects.filter(tag=tag).exists()
                    if not remaining_applications:
                        # If no remaining applications, delete the tag
                        tag.delete()

                    return JsonResponse({'status': 'success', 'action': 'removed'})
                else:
                    # If created, a new tag application was made
                    return JsonResponse({'status': 'success', 'action': 'applied'})

        except Exception as e:
            # Log the exception as needed (optional)
            # logger.error(f"Error modifying tag: {e}")
            return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)

    # If the request method is not POST, return an error
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)


import difflib
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db import IntegrityError
from ..models import Tag, Vote
from ..templatetags.custom_tags import has_tag_edit_permission

def count_word_differences(old_desc, new_desc):
    old_words = old_desc.lower().split()
    new_words = new_desc.lower().split()
    diff = difflib.ndiff(old_words, new_words)
    changes = sum(1 for word in diff if word.startswith('- ') or word.startswith('+ '))
    return changes


def sanitize_description(description):
    # Step 1: Trim leading and trailing spaces
    description = description.strip()
    
    # Step 2: Collapse multiple consecutive spaces into one
    description = ' '.join(description.split())
    
    # Step 3: Reduce consecutive identical characters to two
    description = re.sub(r'(.)\1{2,}', r'\1\1', description)
    
    # Step 4: Unicode normalization to NFC form
    description = unicodedata.normalize('NFC', description)
    
    # Step 5: Remove non-printable and control characters
    description = re.sub(r'[^\x20-\x7E]', '', description)
    
    # Step 6: Remove leading and trailing non-alphanumeric characters
    description = re.sub(r'^[^A-Za-z0-9]+', '', description)
    
    return description

ALLOWED_DESCRIPTION_PATTERN = re.compile(r'^[A-Za-z0-9 .,!?\-_/\'"]{1,255}$')

@login_required
def edit_tags(request):  # Description editing
    user = request.user

    # Check if the user has permission to edit tags
    if not has_tag_edit_permission(user):
        return HttpResponseForbidden("You do not have permission to edit tags.")

    if request.method == 'POST':
        # Handle AJAX tag description updates
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            tag_id = request.POST.get('tag_id')
            new_description = request.POST.get('description', '').strip()
            
            if tag_id and new_description:
                # Sanitize the description
                processed_description = sanitize_description(new_description)
                
                # Validate Description Length
                if len(processed_description) == 0:
                    return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
                if len(processed_description) > 100:
                    return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)
                
                # Validate Allowed Characters using Regex
                if not ALLOWED_DESCRIPTION_PATTERN.match(processed_description):
                    error_message = 'Description contains invalid characters. Allowed characters are letters, numbers, spaces, and basic punctuation (. , ! ? - _ / \' ").'
                    return JsonResponse({'status': 'error', 'message': error_message}, status=400)


                # Check the entire description for profanity
                if profanity.contains_profanity(processed_description):
                    error_message = 'Description contains inappropriate language.'
                    return JsonResponse({'status': 'error', 'message': error_message}, status=400)
                
                tag = get_object_or_404(Tag, id=tag_id)
                old_description = tag.description
                word_diff_count = count_word_differences(old_description, processed_description)
                
                # Update the description
                tag.description = processed_description
                
                # Update description_author if at least 3 words have changed
                if word_diff_count >= 3:
                    tag.description_author = user  # Assign User instance
                
                tag.save()
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Tag description updated.',
                    'word_diff_count': word_diff_count,
                    'description_author': tag.description_author.username if tag.description_author else 'N/A',
                    'upvotes': tag.upvotes,
                    'downvotes': tag.downvotes,
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)
        else:
            return HttpResponseBadRequest("Invalid request method.")

    else:
        # Handle GET requests with search and pagination
        search_query = request.GET.get('search', '').strip()

        if search_query:
            tags = Tag.objects.filter(name__icontains=search_query).order_by('name')
        else:
            tags = Tag.objects.all().order_by('name')

        # Paginate tags
        paginator = Paginator(tags, 20)  # Show 10 tags per page
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'tags': page_obj,  # Pass the Page object to the template
            'search_query': search_query,
        }
        return render(request, 'edit_tags.html', context)

@login_required
def vote_description(request):
    """
    Handle AJAX requests to upvote or downvote a tag's description.
    Supports toggling and switching votes.
    """
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        tag_id = request.POST.get('tag_id')
        vote_type = request.POST.get('vote_type')

        if not tag_id or vote_type not in ['upvote', 'downvote']:
            return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

        tag = get_object_or_404(Tag, id=tag_id)
        user = request.user

        try:
            existing_vote = Vote.objects.get(user=user, tag=tag)
            if existing_vote.vote_type == vote_type:
                # User clicked the same vote button again: Remove the vote
                existing_vote.delete()
                if vote_type == Vote.UPVOTE:
                    tag.upvotes -= 1
                else:
                    tag.downvotes -= 1
                vote_removed = True
                vote_changed = False
                new_vote = False
            else:
                # User clicked the opposing vote button: Change the vote
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

                vote_removed = False
                vote_changed = True
                new_vote = False
        except Vote.DoesNotExist:
            # No existing vote: Create a new vote
            Vote.objects.create(user=user, tag=tag, vote_type=vote_type)
            if vote_type == Vote.UPVOTE:
                tag.upvotes += 1
            else:
                tag.downvotes += 1
            vote_removed = False
            vote_changed = False
            new_vote = True

        # Check if the vote causes the description to be locked
        if (tag.upvotes - tag.downvotes) >= 10:
            tag.is_locked = True
        elif (tag.upvotes - tag.downvotes) < 10 and tag.is_locked:
            tag.is_locked = False  # Optionally unlock if score drops below threshold

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

    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)

ALLOWED_DESCRIPTION_PATTERN = re.compile(r'^[A-Za-z0-9 .,!?\-_/\'"]{1,255}$')

from better_profanity import profanity

@login_required
def update_tag_description(request):
    """
    Handle AJAX requests to update a tag's description.
    """
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        tag_id = request.POST.get('tag_id')
        new_description = request.POST.get('description', '').strip()
        user = request.user

        # Permission Check
        if not has_tag_edit_permission(user):
            return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

        # Validate Tag ID
        tag = get_object_or_404(Tag, id=tag_id)

        # Validate Description Length
        if len(new_description) == 0:
            return JsonResponse({'status': 'error', 'message': 'Description cannot be empty.'}, status=400)
        if len(new_description) > 100:
            return JsonResponse({'status': 'error', 'message': 'Description cannot exceed 100 characters.'}, status=400)

        # Validate Allowed Characters using Regex
        if not ALLOWED_DESCRIPTION_PATTERN.match(new_description):
            error_message = 'Description contains invalid characters. Allowed characters are letters, numbers, spaces, and basic punctuation (. , ! ? - _ / \' ").'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Check the entire description for profanity
        if profanity.contains_profanity(new_description):
            error_message = 'Tag contains inappropriate language.'
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

        # Update Description
        try:
            with transaction.atomic():
                tag.description = new_description
                tag.save()
            return JsonResponse({'status': 'success', 'message': 'Description updated successfully.'})
        except Exception as e:
            # Log the exception as needed (optional)
            return JsonResponse({'status': 'error', 'message': 'Internal server error.'}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request.'}, status=400)
