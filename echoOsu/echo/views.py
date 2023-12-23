from django.shortcuts import render, redirect
from ossapi import Ossapi
from .models import Beatmap, Tag
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from django.shortcuts import redirect
import requests


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
            'client_id': 'YOUR_CLIENT_ID',
            'client_secret': 'YOUR_CLIENT_SECRET',
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'http://127.0.0.1:8000/callback',
        }
        response = requests.post(token_url, data=payload)
        data = response.json()

        # Here you can use the access token from data['access_token']
        # to make API requests or create a user session

        # Redirect to a success page or home page after processing
        return redirect('some_success_page')
    else:
        # Handle the error or redirect to a different page
        return redirect('error_page')

def home(request):
    return render(request, 'home.html')

def beatmap_info(request):
    context = {}

    if request.method == 'POST':
        beatmap_id_request = request.POST.get('beatmap_id')
        if beatmap_id_request:
            beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id_request)

            if created or any(attr is None for attr in [beatmap.title, beatmap.version, beatmap.artist, beatmap.creator, beatmap.cover_image_url, beatmap.total_length, beatmap.bpm, beatmap.cs, beatmap.accuracy, beatmap.ar, beatmap.difficulty_rating]):
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
                    beatmap.accuracy = beatmap_data.accuracy
                    beatmap.ar = beatmap_data.ar
                    beatmap.difficulty_rating = beatmap_data.difficulty_rating

                    beatmap.save()
                    messages.success(request, f"Beatmap {beatmap_id_request} updated.")
                except Exception as e:
                    messages.error(request, f"An error occurred while fetching the beatmap information: {e}")

            context['beatmap'] = beatmap

        if 'tag' in request.POST and beatmap:
            tag_name = request.POST.get('tag')
            tag, created = Tag.objects.get_or_create(name=tag_name)
            beatmap.tags.add(tag)
            messages.success(request, f"Tag '{tag_name}' added to beatmap ID {beatmap_id_request}.")
            return redirect('beatmap_info')

    if 'beatmap' in context:
        beatmap = context['beatmap']
        context['top_tags'] = beatmap.tags.annotate(count=Count('name')).order_by('-count')[:5]
        context['all_tags'] = beatmap.tags.all()

    return render(request, 'beatmap_info.html', context)

def add_tag(request, beatmap_id):
    if request.method == 'POST':
        tag_name = request.POST.get('tag')
        try:
            beatmap = Beatmap.objects.get(beatmap_id=beatmap_id)
            tag, created = Tag.objects.get_or_create(name=tag_name)
            beatmap.tags.add(tag)
            messages.success(request, f"Tag '{tag_name}' added to beatmap ID {beatmap_id}.")
        except Beatmap.DoesNotExist:
            messages.error(request, f"Beatmap ID {beatmap_id} does not exist.")
        return redirect('echo:beatmap_info')

    return redirect('echo:beatmap_info')

def add_tag_to_beatmap(request):
    if request.method == 'POST':
        beatmap_id = request.POST.get('beatmap_id')
        tag_name = request.POST.get('tag')

        try:
            beatmap = Beatmap.objects.get(beatmap_id=beatmap_id)
            tag, created = Tag.objects.get_or_create(name=tag_name)
            beatmap.tags.add(tag)
            if created:
                return JsonResponse({'status': 'tag_created'})
            else:
                return JsonResponse({'status': 'success'})
        except Beatmap.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Beatmap not found'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


def tag_suggestions(request):
    if 'term' in request.GET:
        qs = Tag.objects.filter(name__icontains=request.GET.get('term'))
        titles = list(qs.values_list('name', flat=True))
        return JsonResponse(titles, safe=False)
    
    return JsonResponse([])
    