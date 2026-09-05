
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
from echo.views.shared import GAME_MODE_MAPPING
from echo.views.beatmap import join_diff_creators
from echo.helpers.rosu_utils import get_or_compute_timeseries, get_or_compute_pp, get_or_compute_modded_pps

# Your osu API credentials (from your Django settings)
client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
api = Ossapi(client_id, client_secret)

API_TOKEN = os.getenv('ECHOSU_API_TOKEN', '').strip()
BASE_URL = os.getenv('ECHOSU_BASE_URL', 'https://www.echosu.com').strip()

if not API_TOKEN:
    raise RuntimeError("Missing ECHOSU_API_TOKEN env var (your API token).")

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

        # Prefer resolving by osu_id first; update username if changed
        user_profile = UserProfile.objects.select_related('user').filter(osu_id=osu_id).first()
        if user_profile:
            user = user_profile.user
            if user.username != username:
                conflict_user = User.objects.filter(username=username).exclude(pk=user.pk).first()
                if conflict_user:
                    conflict_user.username = f"{conflict_user.username}__old__{conflict_user.id}"
                    conflict_user.save(update_fields=['username'])
                user.username = username
                user.save(update_fields=['username'])

            if user_profile.profile_pic_url != profile_pic_url:
                user_profile.profile_pic_url = profile_pic_url
                user_profile.save(update_fields=['profile_pic_url'])
        else:
            # No profile for this osu_id yet: try to reuse user by username
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create(username=username)

            existing_profile = getattr(user, 'userprofile', None)
            if existing_profile:
                if existing_profile.osu_id != osu_id or existing_profile.profile_pic_url != profile_pic_url:
                    existing_profile.osu_id = osu_id
                    existing_profile.profile_pic_url = profile_pic_url
                    existing_profile.save(update_fields=['osu_id', 'profile_pic_url'])
            else:
                UserProfile.objects.create(
                    user=user,
                    osu_id=osu_id,
                    profile_pic_url=profile_pic_url
                )

        user_map[osu_id] = user
    return user_map

def fetch_beatmaps(batch_size=500):
    offset = 0
    beatmaps = []
    while True:
        response = requests.get(
            f'{BASE_URL}/api/beatmaps/tags/?batch_size={batch_size}&offset={offset}',
            headers=headers,
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
            tag_name = (tag_info.get('name') or '').strip().lower()
            tag_mode = tag_info.get('mode')  # already normalized in DB (std/taiko/catch/mania)
            if not tag_name:
                continue
            tag, _ = Tag.objects.get_or_create(name=tag_name, mode=Tag.normalize_mode(tag_mode))
            tag_map[(tag_name, tag.mode)] = tag

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

        # Optional fields introduced recently; gracefully handle absence
        timestamp = app.get('timestamp') if isinstance(app, dict) else None
        is_prediction_val = app.get('is_prediction') if isinstance(app, dict) else None
        pred_conf = app.get('prediction_confidence') if isinstance(app, dict) else None

        # Coerce is_prediction to float if provided as bool/int/str
        try:
            if is_prediction_val is not None:
                is_prediction_coerced = float(is_prediction_val)
            else:
                is_prediction_coerced = 0.0
        except Exception:
            is_prediction_coerced = 0.0

        try:
            pred_conf_coerced = float(pred_conf) if pred_conf is not None else None
        except Exception:
            pred_conf_coerced = None

        ta, created = TagApplication.objects.get_or_create(
            beatmap=beatmap,
            tag=tag,
            user=user,
            defaults={
                'timestamp': timestamp if isinstance(timestamp, dict) else None,
                'is_prediction': is_prediction_coerced,
                'prediction_confidence': pred_conf_coerced,
            }
        )
        # Update fields if the record already existed
        if not created:
            fields_to_update = []
            if isinstance(timestamp, dict) and ta.timestamp != timestamp:
                ta.timestamp = timestamp
                fields_to_update.append('timestamp')
            if ta.is_prediction != is_prediction_coerced:
                ta.is_prediction = is_prediction_coerced
                fields_to_update.append('is_prediction')
            if pred_conf_coerced is not None and ta.prediction_confidence != pred_conf_coerced:
                ta.prediction_confidence = pred_conf_coerced
                fields_to_update.append('prediction_confidence')
            if fields_to_update:
                ta.save(update_fields=fields_to_update)

# New function to fetch detailed osu beatmap data
def update_beatmap_details(beatmap_map):
    status_mapping = {
        -2: "Graveyard", -1: "WIP", 0: "Pending",
        1: "Ranked", 2: "Approved", 3: "Qualified", 4: "Loved"
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
            # Preserve original set owner if not already set; compute display creator
            set_owner_name = getattr(beatmapset, 'creator', None)
            set_owner_id = getattr(beatmapset, 'user_id', None)
            if not getattr(beatmap, 'original_creator', None):
                beatmap.original_creator = set_owner_name
            # Always store set owner's id if available
            try:
                beatmap.original_creator_id = str(set_owner_id or '')
            except Exception:
                pass
            try:
                beatmap.creator = join_diff_creators(beatmap_data) or set_owner_name
            except Exception:
                beatmap.creator = set_owner_name
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
            beatmap.max_combo = beatmap_data.max_combo
            beatmap.favourite_count = getattr(beatmapset, 'favourite_count', 0)
            beatmap.mode = GAME_MODE_MAPPING.get(str(beatmap_data.mode), 'unknown')
            # Set per-difficulty last updated timestamp from osu! API
            try:
                beatmap.last_updated = getattr(beatmap_data, 'last_updated', None)
            except Exception:
                beatmap.last_updated = None
            
            # Initialize listed owner/id defaults if missing and not manually overridden
            if not getattr(beatmap, 'listed_owner_is_manual_override', False):
                if not getattr(beatmap, 'listed_owner', None):
                    beatmap.listed_owner = set_owner_name or beatmap.creator
                if not getattr(beatmap, 'listed_owner_id', None):
                    try:
                        beatmap.listed_owner_id = str(set_owner_id or '')
                    except Exception:
                        pass

            beatmap.save()

            # Update genres
            genres = fetch_genres(beatmap.artist, beatmap.title)
            if genres:
                genre_objs = get_or_create_genres(genres)
                beatmap.genres.set(genre_objs)
            else:
                beatmap.genres.clear()

            # Warm and persist rosu-derived caches (best-effort)
            try:
                get_or_compute_timeseries(beatmap, window_seconds=1, mods=None)
            except Exception:
                pass
            try:
                get_or_compute_pp(beatmap)
                get_or_compute_modded_pps(beatmap)
            except Exception:
                pass

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
