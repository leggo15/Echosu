"""
Push local tag data to a live server.

This script reads from the local Django database and uploads:
  1) Predicted tag applications (user is null or is_prediction=True)
  2) User-applied tag applications

Requirements:
  - Run inside this repo's virtualenv with Django deps installed
  - You have an admin-capable API token on the live server (see /api-token/)
  - The live server has ADMIN_OSU_IDS configured to grant staff to your osu_id

Usage (PowerShell):
  python echoOsu/scripts/push_to_prod.py --server https://your-prod-host \
      --token YOUR_TOKEN --push all --batch-size 500

Note: The token should be used as "Authorization: Token <token>".
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests


def bootstrap_django():
    base_dir = Path(__file__).resolve().parents[1]  # echoOsu/
    sys.path.insert(0, str(base_dir))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'echoOsu.settings')
    import django
    django.setup()


def build_session(token: str, timeout: int = 30) -> requests.Session:
    s = requests.Session()
    s.headers.update({'Authorization': f'Token {token}', 'Content-Type': 'application/json'})
    return s


def iter_predictions(batch_size: int):
    from django.db.models import Q
    from echo.models import TagApplication

    qs = (
        TagApplication.objects
        .filter(Q(is_prediction=True) | Q(user__isnull=True))
        .select_related('beatmap', 'tag')
        .order_by('id')
    )

    batch: List[Dict] = []
    for app in qs.iterator(chunk_size=max(1000, batch_size)):
        beatmap_id = getattr(getattr(app, 'beatmap', None), 'beatmap_id', None)
        tag_name = getattr(getattr(app, 'tag', None), 'name', None)
        if not beatmap_id or not tag_name:
            continue
        item = {
            'beatmap_id': str(beatmap_id),
            'tag': str(tag_name).strip().lower(),
        }
        conf = getattr(app, 'prediction_confidence', None)
        if conf is not None:
            item['confidence'] = float(conf)
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def iter_user_applications(batch_size: int):
    from echo.models import TagApplication, UserProfile

    qs = (
        TagApplication.objects
        .filter(user__isnull=False)
        .select_related('beatmap', 'tag', 'user')
        .order_by('id')
    )

    # Prefetch UserProfile map to reduce queries; support missing profiles by resolving on server
    user_ids = list(qs.values_list('user_id', flat=True).distinct())
    profiles = {p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)}

    batch: List[Dict] = []
    for app in qs.iterator(chunk_size=max(1000, batch_size)):
        beatmap_id = getattr(getattr(app, 'beatmap', None), 'beatmap_id', None)
        tag_name = getattr(getattr(app, 'tag', None), 'name', None)
        user = getattr(app, 'user', None)
        if not beatmap_id or not tag_name or not user:
            continue

        profile = profiles.get(getattr(user, 'id', None))
        item: Dict[str, str] = {
            'beatmap_id': str(beatmap_id),
            'tag': str(tag_name).strip().lower(),
        }
        osu_id: Optional[str] = getattr(profile, 'osu_id', None) if profile else None
        if osu_id:
            item['osu_id'] = str(osu_id)
        else:
            # Fallback to username; server will attempt to resolve/create
            username = getattr(user, 'username', None)
            if username:
                item['username'] = str(username)
            else:
                item['user_id'] = str(getattr(user, 'id', ''))

        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def post_batches(session: requests.Session, url: str, key: str, batches, timeout: int = 30):
    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_errors: List[str] = []
    n = 0
    for batch in batches:
        n += 1
        payload = {key: batch} if isinstance(batch, list) else batch
        resp = session.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            total_errors.append(f"HTTP {resp.status_code}: {resp.text}")
            print(f"Batch {n}: ERROR {resp.status_code} -> {resp.text}")
            continue
        data = resp.json() if resp.content else {}
        created = int(data.get('created', 0))
        updated = int(data.get('updated', 0)) if 'updated' in data else 0
        skipped = int(data.get('skipped', 0))
        errors = data.get('errors', []) or []
        total_created += created
        total_updated += updated
        total_skipped += skipped
        total_errors.extend([str(e) for e in errors])
        print(f"Batch {n}: created={created} updated={updated} skipped={skipped} errors={len(errors)}")
    return {
        'created': total_created,
        'updated': total_updated,
        'skipped': total_skipped,
        'errors': total_errors,
    }


def main():
    parser = argparse.ArgumentParser(description='Push local tag data to a live server')
    parser.add_argument('--server', required=True, help='Base URL of the live server (e.g., https://example.com)')
    parser.add_argument('--token', required=True, help='API token (use value from /api-token/)')
    parser.add_argument('--push', choices=['predictions', 'user', 'all'], default='all', help='What to push')
    parser.add_argument('--batch-size', type=int, default=500, help='Batch size per request')
    parser.add_argument('--timeout', type=int, default=30, help='HTTP request timeout (seconds)')
    args = parser.parse_args()

    bootstrap_django()

    base = args.server.rstrip('/')
    s = build_session(args.token, timeout=args.timeout)

    summary = {}

    if args.push in ('predictions', 'all'):
        url = f"{base}/api/admin/upload/predictions/"
        print(f"Uploading predictions to {url} ...")
        res = post_batches(s, url, key='predictions', batches=iter_predictions(args.batch_size), timeout=args.timeout)
        summary['predictions'] = res

    if args.push in ('user', 'all'):
        url = f"{base}/api/admin/upload/tag-applications/"
        print(f"Uploading user tag applications to {url} ...")
        res = post_batches(s, url, key='applications', batches=iter_user_applications(args.batch_size), timeout=args.timeout)
        summary['user_applications'] = res

    print("\nDone.")
    for section, res in summary.items():
        print(f"- {section}: created={res.get('created', 0)} updated={res.get('updated', 0)} skipped={res.get('skipped', 0)} errors={len(res.get('errors', []) or [])}")
        if res.get('errors'):
            print(f"  first error: {res['errors'][0]}")


if __name__ == '__main__':
    main()


