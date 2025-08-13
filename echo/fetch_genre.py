import requests
import time
import urllib.parse
import logging
import os

from .models import Genre, Beatmap

# Configure logging
logger = logging.getLogger(__name__)

# Define the base URL for the MusicBrainz API
BASE_URL = "https://musicbrainz.org/ws/2/"

# headers/User-Agent
HEADERS = {
    "User-Agent": "echosu/0.9 (Richardhansen.no@outlook.com)" 
}

# Rate limiting: one request per second
import requests
import time
import urllib.parse
import logging

from .models import Genre, Beatmap

# Configure logging
logger = logging.getLogger(__name__)

# === MusicBrainz Configuration ===
MB_BASE_URL = "https://musicbrainz.org/ws/2/"

# Headers/User-Agent for MusicBrainz
MB_HEADERS = {
    "User-Agent": "echosu/0.9 (Richardhansen.no@outlook.com)"
}

# === Last.fm Configuration ===
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY', '')  # Provide via environment
LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Rate limiting: one request per second
RATE_LIMIT = 1  # seconds
last_request_time = 0

def rate_limited_request(url, params=None, headers=None):
    """
    Perform a GET request to the specified URL with rate limiting.
    """
    global last_request_time
    elapsed = time.time() - last_request_time
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed)
    try:
        response = requests.get(url, headers=headers, params=params)
        last_request_time = time.time()
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP Request failed: {e} for URL: {url} with params: {params}")
        return None

# === Last.fm Functions ===

def fetch_genres_lastfm(artist, song):
    """
    Fetch genres (tags) for a given artist and song using the Last.fm API.
    """
    # First, try to get tags for the track
    track_tags = get_track_tags_lastfm(artist, song)
    if track_tags:
        print(f"Found tags for track '{song}' by '{artist}': {track_tags}")
        return track_tags

    # If no track tags, try to get tags for the artist
    artist_tags = get_artist_tags_lastfm(artist)
    if artist_tags:
        print(f"Found tags for artist '{artist}': {artist_tags}")
        return artist_tags

    # If no tags found, return empty list
    print(f"No tags found for '{song}' by '{artist}' using Last.fm.")
    return []

def get_track_tags_lastfm(artist, track):
    """
    Get top tags for a track using Last.fm API.
    """
    print(f"Fetching tags for track '{track}' by artist '{artist}' from Last.fm.")
    params = {
        'method': 'track.getTopTags',
        'artist': artist,
        'track': track,
        'api_key': LASTFM_API_KEY,
        'format': 'json'
    }
    data = rate_limited_request(LASTFM_BASE_URL, params=params)
    if data and 'toptags' in data and 'tag' in data['toptags']:
        tags = [tag['name'] for tag in data['toptags']['tag']]
        return tags
    else:
        print(f"No tags found for track '{track}' by '{artist}' on Last.fm.")
        return []

def get_artist_tags_lastfm(artist):
    """
    Get top tags for an artist using Last.fm API.
    """
    print(f"Fetching tags for artist '{artist}' from Last.fm.")
    params = {
        'method': 'artist.getTopTags',
        'artist': artist,
        'api_key': LASTFM_API_KEY,
        'format': 'json'
    }
    data = rate_limited_request(LASTFM_BASE_URL, params=params)
    if data and 'toptags' in data and 'tag' in data['toptags']:
        tags = [tag['name'] for tag in data['toptags']['tag']]
        return tags
    else:
        print(f"No tags found for artist '{artist}' on Last.fm.")
        return []


def search_artist(artist_name):
    """
    Search for an artist by name and return their MusicBrainz ID (MBID).
    """
    print(f"Searching for artist: {artist_name}")
    url = urllib.parse.urljoin(MB_BASE_URL, "artist/")
    params = {
        "query": f'artist:"{artist_name}"',
        "fmt": "json",
        "limit": 1
    }
    data = rate_limited_request(url, params)
    if data and "artists" in data and len(data["artists"]) > 0:
        artist_id = data["artists"][0]["id"]
        print(f"Found artist MBID: {artist_id}")
        return artist_id
    else:
        print(f"Artist '{artist_name}' not found.")
        return None

def search_recording(song_name, artist_mbid):
    """
    Search for a recording by song name and artist MBID, return recording MBID.
    """
    print(f"Searching for recording: {song_name} by artist MBID: {artist_mbid}")
    url = urllib.parse.urljoin(MB_BASE_URL, "recording/")
    params = {
        "query": f'recording:"{song_name}" AND arid:{artist_mbid}',
        "fmt": "json",
        "limit": 1
    }
    data = rate_limited_request(url, params)
    if data and "recordings" in data and len(data["recordings"]) > 0:
        recording_id = data["recordings"][0]["id"]
        print(f"Found recording MBID: {recording_id}")
        return recording_id
    else:
        print(f"Recording '{song_name}' not found for artist MBID '{artist_mbid}'.")
        return None

def get_release_groups_from_recording(recording_mbid):
    """
    Fetch release groups associated with a recording.
    """
    print(f"Fetching release groups for recording MBID: {recording_mbid}")
    url = urllib.parse.urljoin(MB_BASE_URL, f"recording/{recording_mbid}")
    params = {
        "inc": "release-groups",
        "fmt": "json"
    }
    data = rate_limited_request(url, params)
    release_group_ids = []
    if data and "release-groups" in data:
        for rg in data["release-groups"]:
            release_group_ids.append(rg["id"])
        print(f"Found release group IDs: {release_group_ids}")
    else:
        print(f"No release groups found for recording MBID '{recording_mbid}'.")
    return release_group_ids

def get_genres_from_release_group(release_group_mbid):
    """
    Fetch genres associated with a release group using its MBID.
    """
    print(f"Fetching genres for release group MBID: {release_group_mbid}")
    url = urllib.parse.urljoin(MB_BASE_URL, f"release-group/{release_group_mbid}")
    params = {
        "inc": "genres",
        "fmt": "json"
    }
    data = rate_limited_request(url, params)
    if data:
        if "genres" in data and len(data["genres"]) > 0:
            genres = [genre["name"] for genre in data["genres"]]
            print(f"Found genres for release group '{release_group_mbid}': {genres}")
            return genres
        else:
            print(f"No genres found for release group MBID '{release_group_mbid}'.")
            return []
    else:
        print(f"No data received for release group MBID '{release_group_mbid}'.")
        return []
    
def get_genres_from_artist(artist_mbid):
    """
    Fetch genres associated with an artist using their MBID.
    """
    print(f"Fetching genres for artist MBID: {artist_mbid}")
    url = urllib.parse.urljoin(BASE_URL, f"artist/{artist_mbid}")
    params = {
        "inc": "genres",
        "fmt": "json"
    }
    data = rate_limited_request(url, params)
    if data:
        if "genres" in data and len(data["genres"]) > 0:
            genres = [genre["name"] for genre in data["genres"]]
            print(f"Found genres for artist '{artist_mbid}': {genres}")
            return genres
        else:
            print(f"No genres found for artist MBID '{artist_mbid}'.")
            return []
    else:
        print(f"No data received for artist MBID '{artist_mbid}'.")
        return []

def fetch_genres(artist, song):
    """
    Fetch genres for a given artist and song.
    First, attempt to fetch genres using the Last.fm API.
    If that fails, fall back to using MusicBrainz.
    """
    genres = set()  # Use a set to avoid duplicate genres

    # === Attempt to fetch genres from Last.fm ===
    lastfm_genres = fetch_genres_lastfm(artist, song)
    if lastfm_genres:
        genres.update(lastfm_genres)
        print(f"Genres found using Last.fm: {genres}")
        return list(genres)
    else:
        print("No genres found using Last.fm. Falling back to MusicBrainz.")

    # === Fallback to MusicBrainz ===

    # Search for the artist
    artist_mbid = search_artist(artist)
    if not artist_mbid:
        print("No artist MBID found in MusicBrainz. Returning empty genres list.")
        return list(genres)  # Return empty list if artist not found

    # Search for the recording
    recording_mbid = search_recording(song, artist_mbid)
    if not recording_mbid:
        print("No recording MBID found in MusicBrainz. Returning empty genres list.")
        return list(genres)  # Return empty list if recording not found

    # Get release groups from the recording
    release_group_ids = get_release_groups_from_recording(recording_mbid)
    if not release_group_ids:
        print("No release groups found in MusicBrainz. Attempting to fetch artist genres as fallback.")
        # Fallback to artist genres
        mb_genres = get_genres_from_artist(artist_mbid)
        genres.update(mb_genres)
        return list(genres)

    # Fetch genres from each release group
    for rg_id in release_group_ids:
        rg_genres = get_genres_from_release_group(rg_id)
        genres.update(rg_genres)

    if not genres:
        print("No genres found in release groups in MusicBrainz. Attempting to fetch artist genres as fallback.")
        # Fallback to artist genres
        mb_genres = get_genres_from_artist(artist_mbid)
        genres.update(mb_genres)

    return list(genres)

def get_or_create_genres(genre_names):
    """
    Get existing Genre objects or create them if they don't exist.
    """
    genres = []
    for name in genre_names:
        genre, created = Genre.objects.get_or_create(name=name)
        genres.append(genre)
        if created:
            print(f"Created new genre: {name}")
        else:
            print(f"Genre already exists: {name}")
    return genres
