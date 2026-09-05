"""
Push beatmaps (IDs only) to live, letting the server fetch metadata from osu! API.

Usage:
  python echoOsu/scripts/push_maps_to_prod.py --server https://your-live \
      --token YOUR_TOKEN --source local-db --batch-size 500

Or provide a file of IDs:
  python echoOsu/scripts/push_maps_to_prod.py --server https://your-live \
      --token YOUR_TOKEN --file ids.txt

ids.txt format: one beatmap_id per line (numbers only).
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List

import requests


def bootstrap_django():
    base_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base_dir))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'echoOsu.settings')
    import django
    django.setup()


def load_ids_from_file(path: str) -> List[str]:
    ids: List[str] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            val = line.strip()
            if val and val.isdigit():
                ids.append(val)
    return ids


def iter_ids_from_db(batch_size: int) -> Iterable[List[str]]:
    from echo.models import Beatmap
    qs = Beatmap.objects.order_by('id').values_list('beatmap_id', flat=True)
    batch: List[str] = []
    for bm_id in qs.iterator(chunk_size=max(1000, batch_size)):
        if not bm_id:
            continue
        s = str(bm_id)
        if not s.isdigit():
            continue
        batch.append(s)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def post_batches(session: requests.Session, url: str, key: str, batches, timeout: int = 30):
    total_processed = 0
    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_errors = []
    n = 0
    for batch in batches:
        n += 1
        payload = {key: batch}
        resp = session.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            total_errors.append(f"HTTP {resp.status_code}: {resp.text}")
            print(f"Batch {n}: ERROR {resp.status_code} -> {resp.text}")
            continue
        data = resp.json() if resp.content else {}
        processed = int(data.get('processed', 0))
        created = int(data.get('created', 0))
        updated = int(data.get('updated', 0))
        skipped = int(data.get('skipped', 0))
        errs = data.get('errors', []) or []
        total_processed += processed
        total_created += created
        total_updated += updated
        total_skipped += skipped
        total_errors.extend([str(e) for e in errs])
        print(f"Batch {n}: processed={processed} created={created} updated={updated} skipped={skipped} errors={len(errs)}")
    return {
        'processed': total_processed,
        'created': total_created,
        'updated': total_updated,
        'skipped': total_skipped,
        'errors': total_errors,
    }


def main():
    parser = argparse.ArgumentParser(description='Push beatmaps to live (IDs only)')
    parser.add_argument('--server', required=True, help='Base URL of live server')
    parser.add_argument('--token', required=True, help='API token for Authorization: Token <token>')
    parser.add_argument('--source', choices=['local-db', 'file'], default='local-db', help='Where to load IDs from')
    parser.add_argument('--file', help='Path to file with one beatmap_id per line (required if --source file)')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()

    base = args.server.rstrip('/')
    session = requests.Session()
    session.headers.update({'Authorization': f'Token {args.token}', 'Content-Type': 'application/json'})

    if args.source == 'file':
        if not args.file:
            raise SystemExit('--file is required when --source file')
        ids = load_ids_from_file(args.file)
        def batches():
            for i in range(0, len(ids), args.batch_size):
                yield ids[i:i+args.batch_size]
        batches_iter = batches()
    else:
        bootstrap_django()
        batches_iter = iter_ids_from_db(args.batch_size)

    url = f"{base}/api/admin/refresh/beatmaps/"
    print(f"Pushing beatmaps to {url} ...")
    res = post_batches(session, url, key='beatmap_ids', batches=batches_iter, timeout=args.timeout)

    print("\nDone.")
    print(f"processed={res['processed']} created={res['created']} updated={res['updated']} skipped={res['skipped']} errors={len(res['errors'])}")
    if res['errors']:
        print(f"first_error={res['errors'][0]}")


if __name__ == '__main__':
    main()


