
import os
import django
import requests
from ossapi import Ossapi

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "echoOsu.settings")
django.setup()

from echo.models import Beatmap, Tag, TagApplication, UserProfile, Genre
from django.contrib.auth.models import User
from echo.fetch_genre import fetch_genres, get_or_create_genres
from django.conf import settings

# Your osu API credentials (from your Django settings)
client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
api = Ossapi(client_id, client_secret)

API_TOKEN = 'IToYZUbsa6gRvmtoB1kEMTh4kfQ4RRK1L3aMsvtQcwqkVJ1YpvaDpXel9H7T0ucX'
BASE_URL = 'https://www.echosu.com'

headers = {
    'Authorization': f'Token {API_TOKEN}',
    'Content-Type': 'application/json',
}

def fetch_user_profiles():
    response = requests.get(f'{BASE_URL}/api/user-profiles/', headers=headers)
    response.raise_for_status()
    return response.json()

def create_users(user_profiles_data):
    user_map = {}
    for profile_data in user_profiles_data:
        osu_id = profile_data['osu_id']
        username = profile_data['user']['username']
        profile_pic_url = profile_data.get('profile_pic_url', '')

        user, _ = User.objects.get_or_create(username=username)
        user_profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={'osu_id': osu_id, 'profile_pic_url': profile_pic_url}
        )

        if user_profile.profile_pic_url != profile_pic_url or user_profile.osu_id != osu_id:
            user_profile.profile_pic_url = profile_pic_url
            user_profile.osu_id = osu_id
            user_profile.save()

        user_map[osu_id] = user
    return user_map

def fetch_beatmaps(batch_size=500):
    offset = 0
    beatmaps = []
    while True:
        response = requests.get(
            f'{BASE_URL}/api/beatmaps/tags/?batch_size={batch_size}&offset={offset}', 
            headers=headers
        )
        if response.status_code != 200:
            break

        batch_data = response.json()
        if not batch_data:
            break

        beatmaps.extend(batch_data)
        offset += batch_size

    return beatmaps

def fetch_tag_applications():
    response = requests.get(f'{BASE_URL}/api/tag-applications/', headers=headers)
    response.raise_for_status()
    return response.json()

def insert_beatmaps_and_tags(beatmaps_data):
    beatmap_map = {}
    tag_map = {}

    for data in beatmaps_data:
        beatmap, _ = Beatmap.objects.get_or_create(
            beatmap_id=data['beatmap_id'],
            defaults={'title': data['title'], 'artist': data['artist']}
        )
        beatmap_map[data['beatmap_id']] = beatmap

        for tag_info in data['tags']:
            tag_name = tag_info['tag']
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            tag_map[tag_name] = tag

        beatmap.save()
    return beatmap_map, tag_map

def insert_tag_applications(tag_apps_data, beatmap_map, tag_map, user_map):
    for app in tag_apps_data:
        user_username = app['user']['username']
        user = next((u for u in user_map.values() if u.username == user_username), None)

        if not user:
            print(f"Skipping application: User '{user_username}' not found.")
            continue

        beatmap_id = app['beatmap']['beatmap_id']
        tag_name = app['tag']['name']
        beatmap = beatmap_map.get(beatmap_id)
        tag = tag_map.get(tag_name)

        if not beatmap or not tag:
            print(f"Skipping application: Beatmap ({beatmap_id}) or Tag ({tag_name}) missing.")
            continue

        TagApplication.objects.get_or_create(
            beatmap=beatmap,
            tag=tag,
            user=user
        )

# New function to fetch detailed osu beatmap data
def update_beatmap_details(beatmap_map):
    status_mapping = {
        -2: "Graveyard", -1: "WIP", 0: "Pending",
        1: "Ranked", 2: "Approved", 3: "Qualified", 4: "Loved"
    }

    mode_mapping = {
        'GameMode.OSU': 'osu',
        'GameMode.TAIKO': 'taiko',
        'GameMode.CATCH': 'fruits',
        'GameMode.MANIA': 'mania',
    }

    for beatmap_id, beatmap in beatmap_map.items():
        try:
            beatmap_data = api.beatmap(beatmap_id)
            if not beatmap_data:
                print(f"Beatmap ID {beatmap_id} not found in osu API.")
                continue

            beatmapset = beatmap_data._beatmapset

            # Update fields
            beatmap.title = beatmapset.title
            beatmap.artist = beatmapset.artist
            beatmap.creator = beatmapset.creator
            beatmap.cover_image_url = beatmapset.covers.cover_2x
            beatmap.beatmapset_id = beatmapset.id
            beatmap.version = beatmap_data.version 
            beatmap.total_length = beatmap_data.total_length
            beatmap.bpm = beatmap_data.bpm
            beatmap.cs = beatmap_data.cs
            beatmap.drain = beatmap_data.drain
            beatmap.accuracy = beatmap_data.accuracy
            beatmap.ar = beatmap_data.ar
            beatmap.difficulty_rating = beatmap_data.difficulty_rating
            beatmap.status = status_mapping.get(beatmap_data.status.value, "Unknown")
            beatmap.playcount = beatmap_data.playcount
            beatmap.favourite_count = getattr(beatmapset, 'favourite_count', 0)
            beatmap.mode = mode_mapping.get(str(beatmap_data.mode), 'unknown')
            
            beatmap.save()

            # Update genres
            genres = fetch_genres(beatmap.artist, beatmap.title)
            if genres:
                genre_objs = get_or_create_genres(genres)
                beatmap.genres.set(genre_objs)
            else:
                beatmap.genres.clear()

            print(f"Updated beatmap {beatmap_id} successfully.")

        except Exception as e:
            print(f"Error updating beatmap {beatmap_id}: {e}")

if __name__ == '__main__':
    print("Fetching user profiles...")
    user_profiles_data = fetch_user_profiles()
    user_map = create_users(user_profiles_data)

    print("Fetching beatmaps and tags...")
    beatmaps_data = fetch_beatmaps()
    beatmap_map, tag_map = insert_beatmaps_and_tags(beatmaps_data)

    print("Fetching tag applications...")
    tag_apps_data = fetch_tag_applications()
    insert_tag_applications(tag_apps_data, beatmap_map, tag_map, user_map)

    print("Updating detailed beatmap info from osu API...")
    update_beatmap_details(beatmap_map)

    print("Data import and detailed updates completed successfully.")
