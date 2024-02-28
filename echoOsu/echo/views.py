from django.shortcuts import render, redirect
from ossapi import Ossapi
from .models import Beatmap, Tag
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from django.shortcuts import redirect
import requests
from django.contrib.auth.models import User
from django.contrib.auth import login
from .models import UserProfile, TagApplication
from django.conf import settings
from django.db.models import Count, Q
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404

client_id = 28773
client_secret = 'dUzfRmogu3EkymvHr9Hh1lalZRIMyJVmV00U6rSd'
api = Ossapi(client_id, client_secret)

def osu_callback(request):
    # Get the authorization code from the request
    code = request.GET.get('code')

    if code:
        # Exchange the code for an access token
        token_url = 'https://osu.ppy.sh/oauth/token'
        payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'http://127.0.0.1:8000/callback',
        }
        response = requests.post(token_url, data=payload)

        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access_token')

            # Call save_user_data function
            if access_token:
                save_user_data(access_token, request)
                return redirect('beatmap_info')
            else:
                # Handle the case where access token is not present in the response
                messages.error(request, "Failed to retrieve access token.")
                return redirect('error_page')
        else:
            # Handle non-200 responses
            messages.error(request, f"Error during token exchange: {response.status_code}")
            return redirect('error_page')
    else:
        # Handle the case where 'code' is not in GET parameters
        messages.error(request, "Authorization code not found in request.")
        return redirect('error_page')


def admin(request):
    return redirect('/admin/')

def home(request):
    return render(request, 'home.html')

def get_user_data_from_api(access_token):
    url = "https://osu.ppy.sh/api/v2/me"  #URL to osu API for user data
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def save_user_data(access_token, request):
    user_data = get_user_data_from_api(access_token)

    # Assuming 'id' is the correct key for the user's Osu ID. Adjust if necessary.
    osu_id = str(user_data['id'])

    # Find or create the Django user based on the username from the Osu API response
    user, created = User.objects.get_or_create(username=user_data['username'])

    # Update the user's profile with additional details from the Osu API response
    user_profile, profile_created = UserProfile.objects.get_or_create(user=user)
    user_profile.osu_id = osu_id
    user_profile.profile_pic_url = user_data['avatar_url']  # Replace key if different
    user_profile.save()

    # Grant superuser and staff status if the Osu ID is '4978940'
    if osu_id == "4978940":
        user.is_superuser = True
        user.is_staff = True
        user.save()

    # Set the backend to the first in the list from settings
    user.backend = settings.AUTHENTICATION_BACKENDS[0]

    # Log in the user
    login(request, user)
    request.session['osu_id'] = user_data['id']


def beatmap_info(request, beatmap_id=None):
    context = {}
    if beatmap_id:
        beatmap = get_object_or_404(Beatmap, pk=beatmap_id)
    else:
        beatmap = None
    if request.method == 'POST':
        beatmap_id_request = request.POST.get('beatmap_id')
        if beatmap_id_request:
            beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id_request)

            if created or any(attr is None for attr in [beatmap.title, beatmap.version, beatmap.artist, beatmap.creator, beatmap.cover_image_url, beatmap.total_length, beatmap.bpm, beatmap.cs, beatmap.drain, beatmap.accuracy, beatmap.ar, beatmap.difficulty_rating]):
                try:
                    beatmap_data = api.beatmap(beatmap_id_request)

                    if hasattr(beatmap_data, '_beatmapset'):
                        beatmapset = beatmap_data._beatmapset
                        beatmap.title = getattr(beatmapset, 'title', None)
                        beatmap.artist = getattr(beatmapset, 'artist', None)
                        beatmap.creator = getattr(beatmapset, 'creator', None)
                        beatmap.cover_image_url = beatmap_data._beatmapset.covers.cover_2x if hasattr(beatmap_data, '_beatmapset') else None

                    beatmap.version = beatmap_data.version
                    beatmap.total_length = beatmap_data.total_length
                    beatmap.bpm = beatmap_data.bpm
                    beatmap.cs = beatmap_data.cs
                    beatmap.drain = beatmap_data.drain
                    beatmap.accuracy = beatmap_data.accuracy
                    beatmap.ar = beatmap_data.ar
                    beatmap.difficulty_rating = beatmap_data.difficulty_rating

                    beatmap.save()
                    messages.success(request, f"Beatmap {beatmap_id_request} updated.")
                except Exception as e:
                    messages.error(request, f"An error occurred while fetching the beatmap information: {e}")

            context['beatmap'] = beatmap


    if 'beatmap' in context:
        beatmap = context['beatmap']
        
        # Query for user's tags for this beatmap
        user_tag_applications = TagApplication.objects.filter(
            beatmap=beatmap, user=request.user
        )
        user_tags = [tag_app.tag for tag_app in user_tag_applications]

        # Prepare tags with counts and is_applied_by_user flag
        tags_with_counts = []
        for tag in beatmap.tags.all():
            tag_count = TagApplication.objects.filter(tag=tag).count()
            is_applied_by_user = tag in user_tags
            tags_with_counts.append({
                'name': tag.name,
                'apply_count': tag_count,
                'is_applied_by_user': is_applied_by_user
            })

        context['tags_with_counts'] = tags_with_counts

    return render(request, 'beatmap_info.html', {'beatmap': beatmap})




def search_tags(request):
    search_query = request.GET.get('q', '')
    tags = Tag.objects.filter(name__icontains=search_query).annotate(beatmap_count=Count('beatmaps')).values('name', 'beatmap_count')
    return JsonResponse(list(tags), safe=False)


def get_tags(request):
    beatmap_id = request.GET.get('beatmap_id')
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # This query will get all tags for this beatmap along with a count of distinct users that applied each tag.
    tags_with_user_counts = TagApplication.objects.filter(beatmap=beatmap).values('tag__name').annotate(apply_count=Count('user', distinct=True)).order_by('tag__name')

    # Convert the query to a list of dictionaries
    tags_with_counts_list = [
        {'name': tag['tag__name'], 'apply_count': tag['apply_count']} for tag in tags_with_user_counts
    ]
    return JsonResponse(tags_with_counts_list, safe=False)



def search_tags(request):
    # Get the search query from the request's GET parameters
    search_query = request.GET.get('q', '')

    # Filter tags based on the search query (case insensitive matching)
    tags = Tag.objects.filter(name__icontains=search_query).annotate(beatmap_count=Count('beatmaps')).values('name', 'beatmap_count')

    # Return the list of matching tags as JSON
    return JsonResponse(list(tags), safe=False)


@csrf_exempt
@login_required
def apply_tag(request):
    if request.method == 'POST':
        tag_name = request.POST.get('tag')
        beatmap_id = request.POST.get('beatmap_id')

        tag, created = Tag.objects.get_or_create(name=tag_name)
        beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

        # Create a new TagApplication instance
        tag_application = TagApplication.objects.create(
            tag=tag, 
            beatmap=beatmap, 
            user=request.user  # Setting the user
        )

        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)


def profile(request):
    # Ensure the user is logged in
    if not request.user.is_authenticated:
        # Redirect to login page or show an error
        # Get all TagApplications for the current user
        user_tags = TagApplication.objects.filter(user=request.user).select_related('beatmap')
    # Pass the user_tags to the template
    return render(request, 'profile.html', {'user_tags': user_tags})


def search_results(request):
    # Get the search query from the request
    query = request.GET.get('query', '').strip()

    # Initialize an empty queryset
    beatmaps = Beatmap.objects.none()

    if query:
        # First, try to match tags
        tags = Tag.objects.filter(name__icontains=query)
        if tags.exists():
            beatmaps = Beatmap.objects.filter(tags__in=tags).distinct()
        else:
            # If no tags match, search other beatmap attributes
            beatmaps = Beatmap.objects.filter(
                Q(beatmap_id__icontains=query) |
                Q(title__icontains=query) |
                Q(creator__icontains=query) |
                Q(artist__icontains=query)
            ).distinct()

        # Annotate the beatmaps with the number of users who have applied tags, if needed
        beatmaps = beatmaps.annotate(num_users=Count('tags__tagapplication__user', distinct=True)).order_by('-num_users')
    else:
        # If there is no query, decide on the behavior. This example returns no results.
        # If you want to return all beatmaps by default, you can use Beatmap.objects.all() instead
        beatmaps = Beatmap.objects.none()

    return render(request, 'search_results.html', {'beatmaps': beatmaps})


def beatmap_detail(request, beatmap_id):
    beatmap = get_object_or_404(Beatmap, beatmap_id=beatmap_id)

    # If you have a model to track tag applications, you can query for tags applied to this beatmap
    tags_with_counts = TagApplication.objects.filter(beatmap=beatmap).values('tag__name').annotate(apply_count=Count('id')).order_by('-apply_count')

    # Example for handling tag addition (simplified, adjust according to your actual logic and models)
    if request.method == 'POST' and 'tag_name' in request.POST:
        tag_name = request.POST.get('tag_name')
        # Here you would add logic to create a TagApplication for this beatmap and tag

    return render(request, 'beatmap_detail.html', {'beatmap': beatmap, 'tags_with_counts': tags_with_counts})