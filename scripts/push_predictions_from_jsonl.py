#!/usr/bin/env python3
"""
Push predicted tags from a JSONL file to prod.
- Ensures beatmaps exist in prod (and refreshes full metadata) before uploading predictions.
- Sends predictions in batches (default 10).
- Supports an ignore list of tags and a minimum number of predictions per map.

Usage (Windows cmd example):
  py -3 push_predictions_from_jsonl.py --server https://echosu.com --token ToDZQnOg8GULovYHz6eZ0WJZUYOSh1wcNRBXlZFjyj9B3nFDhXhazRzj0LOzhr0L --batch-size 10

Notes:
- The JSONL must contain one JSON object per line like:
    {"map_id": 352673, "predictions": {"flow": 0.7011}}
- For each map, we POST its ID to /api/admin/refresh/beatmaps/ (to fetch full metadata),
  then POST its predicted tags to /api/admin/upload/predictions/.
"""

import argparse
import json
import sys
import requests
from typing import Dict, Iterable, List, Tuple, Set


# ==== CONFIG ====
PREDICTIONS_FILE = "tag_predictions.jsonl"  # Path to your JSONL
IGNORE_TAGS = {"complex rhythms", "2b", "deathstream"}  # Lowercase tags to skip
MIN_TAGS_REQUIRED = 3  # Minimum non-ignored predicted tags to upload
# =================


def build_session(token: str) -> requests.Session:
    s = requests.Session()
    # DRF custom token auth header, matches server expectation.
    s.headers.update({'Authorization': f'Token {token}', 'Content-Type': 'application/json'})
    return s

def batched(seq: List, size: int) -> Iterable[List]:
    for i in range(0, len(seq), size):
        yield seq[i:i+size]

def load_jsonl(path: str) -> List[Dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"Line {ln}: invalid JSON -> {e}")
            # Normalize expected shape
            map_id = obj.get("map_id") or obj.get("beatmap_id") or obj.get("id")
            preds = obj.get("predictions") or obj.get("tags")
            if map_id is None or preds is None:
                raise SystemExit(f"Line {ln}: missing required fields. Need map_id and predictions.")
            if not isinstance(preds, dict):
                raise SystemExit(f"Line {ln}: 'predictions' must be a dict of tag->confidence.")
            items.append({"beatmap_id": str(map_id), "predictions": preds})
    return items

def filter_and_transform(items: List[Dict], ignore: Set[str], min_tags: int) -> Tuple[List[Dict], List[str]]:
    """
    Returns (payload_items, beatmap_ids) where payload_items is a list in the shape
    accepted by /api/admin/upload/predictions/, using the "tags" list format:
      {"beatmap_id": "123", "tags": [{"tag":"aim","confidence":0.98}, ...]}
    """
    payload = []
    ids = []
    for it in items:
        bm_id = str(it["beatmap_id"]).strip()
        preds: Dict[str, float] = it["predictions"]
        # Lowercase + strip tag names, drop ignored
        pairs = []
        for k, v in preds.items():
            name = str(k).strip().lower()
            if name in ignore:
                continue
            try:
                conf = float(v)
            except Exception:
                # Skip non-numeric confidences
                continue
            pairs.append({"tag": name, "confidence": conf})
        if len(pairs) < min_tags:
            continue
        payload.append({"beatmap_id": bm_id, "tags": pairs})
        ids.append(bm_id)
    return payload, ids

def post_json(session: requests.Session, url: str, data, timeout: int) -> dict:
    resp = session.post(url, json=data, timeout=timeout)
    if resp.status_code >= 400:
        raise SystemExit(f"{url} -> HTTP {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}

def main():
    ap = argparse.ArgumentParser(description="Push predicted tags from JSONL to prod (in batches).")
    ap.add_argument("--server", required=True, help="Base server URL")
    ap.add_argument("--token", required=True, help="Admin API token")
    ap.add_argument("--batch-size", type=int, default=10, help="Batch size for uploads")
    ap.add_argument("--timeout", type=int, default=180, help="HTTP timeout seconds")
    ap.add_argument("--dry-run", type=int, default=0, help="If 1, do not POST; just print what would happen")
    args = ap.parse_args()

    base = args.server.rstrip("/")
    ignore = {t.strip().lower() for t in args.ignore.split(",") if t.strip()}
    session = build_session(args.token)

    print(f"Loading JSONL: {args.file}")
    raw_items = load_jsonl(PREDICTIONS_FILE)
    print(f"Loaded {len(raw_items)} lines from {PREDICTIONS_FILE}")

    print(f"Filtering with ignore={sorted(IGNORE_TAGS)} and min_tags={MIN_TAGS_REQUIRED}")
    items, all_ids = filter_and_transform(raw_items, IGNORE_TAGS, MIN_TAGS_REQUIRED)
    print(f"After filtering: {len(items)} maps ({len(all_ids)} ids) will be processed")

    if not items:
        print("Nothing to upload after filtering. Exiting.")
        return

    # Process in batches by map (each item = one beatmap with its tags)
    batch_no = 0
    for batch in batched(items, args.batch_size):
        batch_no += 1
        beatmap_ids = [x["beatmap_id"] for x in batch]

        # 1) Ensure beatmaps (with full metadata) exist on prod
        refresh_url = f"{base}/api/admin/refresh/beatmaps/"
        refresh_payload = {"beatmap_ids": beatmap_ids}
        print(f"[Batch {batch_no}] Refreshing beatmaps: {beatmap_ids}")
        if not args.dry_run:
            r = post_json(session, refresh_url, refresh_payload, args.timeout)
            print(f"[Batch {batch_no}] refresh -> {r}")
        else:
            print(f"[DRY RUN] Would POST to {refresh_url} with {refresh_payload}")

        # 2) Upload predictions using the 'items' wrapper and 'tags' list shape
        up_url = f"{base}/api/admin/upload/predictions/"
        upload_payload = {"items": batch}
        print(f"[Batch {batch_no}] Uploading predictions for {len(batch)} map(s)")
        if not args.dry_run:
            r = post_json(session, up_url, upload_payload, args.timeout)
            print(f"[Batch {batch_no}] upload -> {r}")
        else:
            print(f"[DRY RUN] Would POST to {up_url} with {upload_payload}")

    print("Done.")

if __name__ == "__main__":
    main()
