"""
Push order: users -> beatmaps -> predictions -> user tag applications.

Usage:
  python echoOsu/scripts/push_all_to_prod.py --server https://your-live \
      --token YOUR_TOKEN --batch-size 10 --source local-db

Alternatively, provide files for users/ids:
  --users-file users.json  (list of {osu_id, username, profile_pic_url})
  --ids-file ids.txt       (one beatmap_id per line)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests


def bootstrap_django():
    base_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base_dir))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'echoOsu.settings')
    import django
    django.setup()


def build_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({'Authorization': f'Token {token}', 'Content-Type': 'application/json'})
    return s


def iter_local_users(batch_size: int):
    from echo.models import UserProfile
    batch: List[Dict] = []
    qs = UserProfile.objects.select_related('user').order_by('id')
    for p in qs.iterator(chunk_size=max(1000, batch_size)):
        if not p.osu_id:
            continue
        batch.append({
            'osu_id': str(p.osu_id),
            'username': p.user.username,
            'profile_pic_url': p.profile_pic_url or '',
        })
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def iter_ids_from_db(batch_size: int):
    from echo.models import Beatmap
    batch: List[str] = []
    for bm_id in Beatmap.objects.order_by('id').values_list('beatmap_id', flat=True).iterator(chunk_size=max(1000, batch_size)):
        s = str(bm_id)
        if not s.isdigit():
            continue
        batch.append(s)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


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
        bm_id = getattr(getattr(app, 'beatmap', None), 'beatmap_id', None)
        tag_name = getattr(getattr(app, 'tag', None), 'name', None)
        if not bm_id or not tag_name:
            continue
        item = {'beatmap_id': str(bm_id), 'tag': str(tag_name).strip().lower()}
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
    user_ids = list(qs.values_list('user_id', flat=True).distinct())
    profiles = {p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)}
    batch: List[Dict] = []
    for app in qs.iterator(chunk_size=max(1000, batch_size)):
        bm = getattr(app, 'beatmap', None)
        tg = getattr(app, 'tag', None)
        us = getattr(app, 'user', None)
        if not bm or not tg or not us:
            continue
        prof = profiles.get(getattr(us, 'id', None))
        item = {'beatmap_id': str(bm.beatmap_id), 'tag': str(tg.name).strip().lower()}
        osu_id: Optional[str] = getattr(prof, 'osu_id', None) if prof else None
        if osu_id:
            item['osu_id'] = str(osu_id)
        else:
            username = getattr(us, 'username', None)
            if username:
                item['username'] = str(username)
            else:
                item['user_id'] = str(getattr(us, 'id', ''))
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def post_batches(session: requests.Session, url: str, key: str, batches, timeout: int = 180):
    n = 0
    for batch in batches:
        n += 1
        payload = {key: batch}
        resp = session.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            raise SystemExit(f"{url} -> HTTP {resp.status_code}: {resp.text}")
        data = resp.json() if resp.content else {}
        created = data.get('created') or data.get('processed')
        print(f"Batch {n}: {data} (created/processed={created})")


def main():
    parser = argparse.ArgumentParser(description='Push users, beatmaps, predictions, and tag apps to live')
    parser.add_argument('--server', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--source', choices=['local-db'], default='local-db')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--users-file')
    parser.add_argument('--ids-file')
    args = parser.parse_args()

    base = args.server.rstrip('/')
    session = build_session(args.token)

    bootstrap_django()

    # 1) Users
    print('Uploading users ...')
    if args.users_file:
        with open(args.users_file, 'r', encoding='utf-8') as f:
            users = json.load(f)
        def ub():
            for i in range(0, len(users), args.batch_size):
                yield users[i:i+args.batch_size]
        post_batches(session, f"{base}/api/admin/upload/users/", key='users', batches=ub(), timeout=args.timeout)
    else:
        post_batches(session, f"{base}/api/admin/upload/users/", key='users', batches=iter_local_users(args.batch_size), timeout=args.timeout)

    # 2) Beatmaps
    print('Uploading beatmaps ...')
    if args.ids_file:
        with open(args.ids_file, 'r', encoding='utf-8') as f:
            ids = [l.strip() for l in f if l.strip() and l.strip().isdigit()]
        def ib():
            for i in range(0, len(ids), args.batch_size):
                yield ids[i:i+args.batch_size]
        post_batches(session, f"{base}/api/admin/refresh/beatmaps/", key='beatmap_ids', batches=ib(), timeout=args.timeout)
    else:
        post_batches(session, f"{base}/api/admin/refresh/beatmaps/", key='beatmap_ids', batches=iter_ids_from_db(args.batch_size), timeout=args.timeout)

    # 3) Predictions
    print('Uploading predictions ...')
    post_batches(session, f"{base}/api/admin/upload/predictions/", key='predictions', batches=iter_predictions(args.batch_size), timeout=args.timeout)

    # 4) User tag applications
    print('Uploading user tag applications ...')
    post_batches(session, f"{base}/api/admin/upload/tag-applications/", key='applications', batches=iter_user_applications(args.batch_size), timeout=args.timeout)

    print('Done.')


if __name__ == '__main__':
    main()



