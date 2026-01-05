from __future__ import annotations

import json
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_POST
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from django.db.models import F
from django.conf import settings

import hmac
import hashlib

from ..models import AnalyticsSearchEvent, AnalyticsClickEvent, Beatmap


def _get_client_id(request: HttpRequest) -> str | None:
	# Anonymous client identifier set by middleware; not tied to a user account
	return request.COOKIES.get('analytics_id')

def _hash_user_id(user_id: int | str | None) -> str | None:
	"""
	Return a stable, non-reversible identifier for an authenticated user.
	We HMAC the user id using SECRET_KEY so it can't be reversed without server secret.
	"""
	try:
		if user_id is None:
			return None
		uid = str(int(user_id)).strip()
		if not uid:
			return None
	except Exception:
		return None
	try:
		secret = str(getattr(settings, 'SECRET_KEY', '') or '')
	except Exception:
		secret = ''
	if not secret:
		# Should never happen in real deployments; fail closed (treat as anonymous).
		return None
	msg = ('echo-analytics:uid:' + uid).encode('utf-8')
	return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()


@require_POST
def log_search_event(request: HttpRequest):
	"""
	Log an anonymous search event.
	Expected JSON body:
	{
	  "query": str,
	  "tags": [str] | null,
	  "results_count": int,
	  "sort": str,
	  "predicted_mode": str,
	  "flags": { ... } | null
	}
	Returns: { "ok": true, "event_id": "<uuid>" }
	"""
	try:
		payload: Dict[str, Any] = json.loads(request.body.decode('utf-8') or '{}')
	except Exception:
		payload = {}

	client_id = _get_client_id(request)
	query = (payload.get('query') or '')[:1000]
	# Ignore empty-query searches entirely for analytics (no log, no graphs)
	if not (query or '').strip():
		return JsonResponse({'ok': False})
	tags = payload.get('tags')
	if tags is not None and not isinstance(tags, (list, dict)):
		try:
			tags = list(tags)
		except Exception:
			tags = None
	results_count = payload.get('results_count')
	try:
		results_count = int(results_count)
	except Exception:
		results_count = None
	sort = (payload.get('sort') or '')[:32]
	predicted_mode = (payload.get('predicted_mode') or '')[:16]
	search_mode = (payload.get('mode') or '').strip().lower()
	flags = payload.get('flags') if isinstance(payload.get('flags'), (dict, list)) else None
	if search_mode:
		if not isinstance(flags, dict):
			flags = {}
		flags['mode'] = search_mode

	user = getattr(request, 'user', None)
	logged_in_user_id = None
	is_staff = False
	try:
		if getattr(user, 'is_authenticated', False):
			logged_in_user_id = _hash_user_id(getattr(user, 'id', None))
			is_staff = bool(getattr(user, 'is_staff', False))
	except Exception:
		logged_in_user_id = None
		is_staff = False

	se = AnalyticsSearchEvent.objects.create(
		client_id=client_id,
		logged_in_user_id=logged_in_user_id,
		is_staff=is_staff,
		query=query,
		tags=tags,
		results_count=results_count,
		sort=sort,
		predicted_mode=predicted_mode,
		flags=flags,
	)
	return JsonResponse({'ok': True, 'event_id': str(se.event_id), 'ts': int(now().timestamp())})


@require_POST
def log_click_event(request: HttpRequest):
	"""
	Log an anonymous click/interaction event within the search results feed.
	Expected JSON body:
	{
	  "action": str,                // e.g., "direct", "beatconnect", "view_details", "view_on_osu", "find_similar"
	  "beatmap_id": str | int | null,
	  "search_event_id": str | null,
	  "meta": { ... } | null
	}
	Returns: { "ok": true }
	"""
	try:
		payload: Dict[str, Any] = json.loads(request.body.decode('utf-8') or '{}')
	except Exception:
		payload = {}

	client_id = _get_client_id(request)
	action = (payload.get('action') or '')[:64]
	beatmap_id_raw = payload.get('beatmap_id')
	beatmap_id: str | None
	if beatmap_id_raw is None:
		beatmap_id = None
	else:
		beatmap_id = str(beatmap_id_raw)[:64]
	search_event_id = payload.get('search_event_id') or None
	meta = payload.get('meta') if isinstance(payload.get('meta'), (dict, list)) else None

	user = getattr(request, 'user', None)
	logged_in_user_id = None
	is_staff = False
	try:
		if getattr(user, 'is_authenticated', False):
			logged_in_user_id = _hash_user_id(getattr(user, 'id', None))
			is_staff = bool(getattr(user, 'is_staff', False))
	except Exception:
		logged_in_user_id = None
		is_staff = False

	AnalyticsClickEvent.objects.create(
		client_id=client_id,
		logged_in_user_id=logged_in_user_id,
		is_staff=is_staff,
		action=action,
		beatmap_id=beatmap_id,
		search_event_id=search_event_id,
		meta=meta,
	)
	# Increment persistent impression counter for beatmaps.
	# This is safe to fire for anonymous events; it's just aggregate stats.
	try:
		if action == 'impression' and beatmap_id:
			Beatmap.objects.filter(beatmap_id=str(beatmap_id)).update(shown_in_search=F('shown_in_search') + 1)
	except Exception:
		pass
	return JsonResponse({'ok': True})


@require_POST
def log_impressions(request: HttpRequest):
	"""
	Increment Beatmap.shown_in_search for a batch of beatmap ids that were visible on a search results page.
	Expected JSON body:
	{
	  "beatmap_ids": [str|int],
	  "search_event_id": str | null,
	  "page": int | null
	}
	"""
	try:
		payload: Dict[str, Any] = json.loads(request.body.decode('utf-8') or '{}')
	except Exception:
		payload = {}

	beatmap_ids = payload.get('beatmap_ids') or []
	if not isinstance(beatmap_ids, list):
		beatmap_ids = []
	# De-duplicate and sanitize
	ids = []
	seen = set()
	for v in beatmap_ids:
		try:
			s = str(v).strip()
			if not s:
				continue
			if s in seen:
				continue
			seen.add(s)
			ids.append(s)
		except Exception:
			continue

	if not ids:
		return JsonResponse({'ok': True, 'updated': 0})

	try:
		updated = Beatmap.objects.filter(beatmap_id__in=ids).update(shown_in_search=F('shown_in_search') + 1)
	except Exception:
		updated = 0
	return JsonResponse({'ok': True, 'updated': int(updated)})

