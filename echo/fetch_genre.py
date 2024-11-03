import requests
import time
import urllib.parse
import logging

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
RATE_LIMIT = 1  # seconds
last_request_time = 0

def rate_limited_request(url, params=None):
    """
    Perform a GET request to the specified URL with rate limiting.
    """
    global last_request_time
    elapsed = time.time() - last_request_time
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed)
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        last_request_time = time.time()
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP Request failed: {e} for URL: {url} with params: {params}")
        return None

def search_artist(artist_name):
    """
    Search for an artist by name and return their MusicBrainz ID (MBID).
    """
    print(f"Searching for artist: {artist_name}")
    url = urllib.parse.urljoin(BASE_URL, "artist/")
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
    url = urllib.parse.urljoin(BASE_URL, "recording/")
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
    url = urllib.parse.urljoin(BASE_URL, f"recording/{recording_mbid}")
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
    url = urllib.parse.urljoin(BASE_URL, f"release-group/{release_group_mbid}")
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

def fetch_genres(artist, song):
    """
    Fetch genres for a given artist and song.
    This function fetches genres from the release groups associated with the recording.
    If no genres are found at the release group level, it falls back to artist genres.
    """
    genres = set()  # Use a set to avoid duplicate genres

    # Search for the artist
    artist_mbid = search_artist(artist)
    if not artist_mbid:
        print("No artist MBID found. Returning empty genres list.")
        return list(genres)  # Return empty list if artist not found

    # Search for the recording
    recording_mbid = search_recording(song, artist_mbid)
    if not recording_mbid:
        print("No recording MBID found. Returning empty genres list.")
        return list(genres)  # Return empty list if recording not found

    # Get release groups from the recording
    release_group_ids = get_release_groups_from_recording(recording_mbid)
    if not release_group_ids:
        print("No release groups found. Attempting to fetch artist genres as fallback.")
        # Fallback to artist genres
        genres = get_genres_from_artist(artist_mbid)
        return list(genres)

    # Fetch genres from each release group
    for rg_id in release_group_ids:
        rg_genres = get_genres_from_release_group(rg_id)
        genres.update(rg_genres)

    if not genres:
        print("No genres found in release groups. Attempting to fetch artist genres as fallback.")
        # Fallback to artist genres
        genres = get_genres_from_artist(artist_mbid)

    return list(genres)

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