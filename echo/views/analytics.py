from __future__ import annotations

import json
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_POST
from django.utils.timezone import now

from ..models import AnalyticsSearchEvent, AnalyticsClickEvent


def _get_client_id(request: HttpRequest) -> str | None:
	# Anonymous client identifier set by middleware; not tied to a user account
	return request.COOKIES.get('analytics_id')


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
	flags = payload.get('flags') if isinstance(payload.get('flags'), (dict, list)) else None

	se = AnalyticsSearchEvent.objects.create(
		client_id=client_id,
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

	AnalyticsClickEvent.objects.create(
		client_id=client_id,
		action=action,
		beatmap_id=beatmap_id,
		search_event_id=search_event_id,
		meta=meta,
	)
	return JsonResponse({'ok': True})

