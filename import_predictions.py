import os
import django
import json
from ossapi import Ossapi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "echoOsu.settings")
django.setup()

from echo.models import Beatmap, Tag, TagApplication
from django.conf import settings

client_id = settings.SOCIAL_AUTH_OSU_KEY
client_secret = settings.SOCIAL_AUTH_OSU_SECRET
api = Ossapi(client_id, client_secret)

PREDICTIONS_PATH = "tag_predictions.jsonl"

def fetch_and_create_beatmap(map_id):
    bm = api.beatmap(map_id)
    if bm is None:
        print(f"Could not fetch beatmap {map_id} from osu! API.")
        return None
    beatmap, created = Beatmap.objects.get_or_create(
        beatmap_id=str(bm.id),
        defaults={
            "title": getattr(bm._beatmapset, "title", ""),
            "artist": getattr(bm._beatmapset, "artist", ""),
            "version": getattr(bm, "version", ""),
            "creator": getattr(bm._beatmapset, "creator", ""),
            "cover_image_url": getattr(getattr(bm._beatmapset, "covers", None), "cover_2x", ""),
            "mode": str(bm.mode) if hasattr(bm, "mode") else "osu",
            "bpm": getattr(bm, "bpm", None),
            "ar": getattr(bm, "ar", None),
            "cs": getattr(bm, "cs", None),
            "drain": getattr(bm, "drain", None),
            "accuracy": getattr(bm, "accuracy", None),
            "difficulty_rating": getattr(bm, "difficulty_rating", None),
            "status": str(bm.status) if hasattr(bm, "status") else "",
            "total_length": getattr(bm, "total_length", None),
            "playcount": getattr(bm, "playcount", None),
            "favourite_count": getattr(getattr(bm._beatmapset, "favourite_count", 0), "__int__", lambda: 0)(),
        }
    )
    # Regardless of created or fetched, update with details
    # This is the core of your update_beatmap_details for one map:
    try:
        beatmapset = bm._beatmapset
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

        beatmap.title = beatmapset.title
        beatmap.artist = beatmapset.artist
        beatmap.creator = beatmapset.creator
        beatmap.cover_image_url = beatmapset.covers.cover_2x
        beatmap.beatmapset_id = beatmapset.id
        beatmap.version = bm.version
        beatmap.total_length = bm.total_length
        beatmap.bpm = bm.bpm
        beatmap.cs = bm.cs
        beatmap.drain = bm.drain
        beatmap.accuracy = bm.accuracy
        beatmap.ar = bm.ar
        beatmap.difficulty_rating = bm.difficulty_rating
        beatmap.status = status_mapping.get(bm.status.value, "Unknown")
        beatmap.playcount = bm.playcount
        beatmap.favourite_count = getattr(beatmapset, 'favourite_count', 0)
        beatmap.mode = mode_mapping.get(str(bm.mode), 'unknown')

        # Save!
        beatmap.save()
    except Exception as e:
        print(f"Error updating details for beatmap {map_id}: {e}")
    return beatmap



def import_predictions_with_beatmap_creation():
    total = 0
    created = 0
    with open(PREDICTIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            data = json.loads(line)
            map_id = str(data["map_id"])
            preds = data.get("predictions", {})

            # Get or create the Beatmap
            try:
                beatmap = Beatmap.objects.get(beatmap_id=map_id)
            except Beatmap.DoesNotExist:
                print(f"Beatmap {map_id} not found. Fetching from osu! API...")
                beatmap = fetch_and_create_beatmap(map_id)
                if not beatmap:
                    print(f"Skipping map {map_id} (could not fetch/create).")
                    continue

            for tag_name, confidence in preds.items():
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                app, was_created = TagApplication.objects.get_or_create(
                    tag=tag,
                    beatmap=beatmap,
                    user=None,
                    defaults={
                        "is_prediction": True,
                        "prediction_confidence": confidence,
                    }
                )
                # If already exists as a prediction, update confidence
                if not was_created and app.is_prediction:
                    app.prediction_confidence = confidence
                    app.save(update_fields=["prediction_confidence"])
                if was_created:
                    created += 1

    print(f"Processed {total} maps, created/updated {created} predicted TagApplications.")

if __name__ == "__main__":
    import_predictions_with_beatmap_creation()
