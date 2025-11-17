# echosu/views/api.py
"""API views for beatmaps, tags, and user profiles.
This module provides endpoints for fetching beatmaps, tags, and user profiles,
as well as managing tag applications.
It includes both Django viewsets for the REST API and helper functions for
tag management.
"""


# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

# ---------------------------------------------------------------------------
# REST framework imports
# ---------------------------------------------------------------------------
from rest_framework import status, viewsets
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from django.core.cache import cache
from django.utils import timezone

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..authentication import CustomTokenAuthentication
from ..models import (
    Beatmap,
    CustomToken,
    Tag,
    TagApplication,
    UserProfile,
)
from ..serializers import (
    BeatmapSerializer,
    TagApplicationSerializer,
    TagApplicationLiteSerializer,
    TagApplicationToggleSerializer,
    TagSerializer,
    UserProfileSerializer,
)
from .auth import api                         # shared Ossapi instance
from .beatmap import join_diff_creators       # helper
from .shared import GAME_MODE_MAPPING         # mode mapping helper
from ..helpers.timestamps import consensus_intervals, normalize_intervals
# --------------------------------------------------------------------- #


# ----------------------------- Helper endpoints ----------------------------- #

@api_view(['GET'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def tags_for_beatmaps(request, beatmap_id=None):
    # Deprecated in favor of /api/tag-applications/?beatmap_id=...&include=tag_counts
    return Response({'detail': 'Deprecated. Use /api/tag-applications/?beatmap_id={id}&include=tag_counts'}, status=410)


# ----------------------------- Token helper ----------------------------- #

# Removed: superseded by echo.views.userSettings.settings


# ----------------------------- API ViewSets ----------------------------- #

class BeatmapViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Beatmap.objects.all()
    serializer_class = BeatmapSerializer
    authentication_classes = [CustomTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    # Allow lookup by beatmap_id string instead of internal pk for clarity
    lookup_field = 'beatmap_id'
    lookup_value_regex = '[0-9]+'

    @action(detail=False, methods=['get'], url_path='filtered')
    def filtered(self, request):
        query = request.query_params.get('query')
        if not query:
            return Response(
                {'detail': "Query parameter 'query' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        beatmaps = Beatmap.objects.filter(
            Q(title__icontains=query)
            | Q(artist__icontains=query)
            | Q(tags__name__icontains=query)
        ).distinct()
        return Response(self.get_serializer(beatmaps, many=True).data)

    # retrieve remains the default: only beatmap fields
    # All tag data is provided via /api/tag-applications/?beatmap_id=... with include=...


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    authentication_classes = [CustomTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]


class TagApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TagApplication.objects.all()
    serializer_class = TagApplicationSerializer
    authentication_classes = [CustomTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_permissions(self):
        """Allow unauthenticated read-only access when filtered by beatmap.
        This enables public viewing of consensus tag timestamps on beatmap pages,
        while keeping all write operations and unfiltered access locked down.
        """
        try:
            if self.action == 'list' and self.request.method == 'GET' and 'beatmap_id' in self.request.query_params:
                return [AllowAny()]
        except Exception:
            pass
        return [IsAuthenticated()]
    
    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        include_tokens = [s.strip() for s in (params.get('include') or '').split(',') if s.strip()]
        include_predicted_flag = ('predicted_tags' in include_tokens) or (str(params.get('include_predicted', '0')).lower() in ['1', 'true', 'yes', 'on', 'include'])
        include_true_negatives_flag = ('true_negatives' in include_tokens) or ('negative_tags' in include_tokens)
        # Always drop null-user non-predicted records
        qs = qs.exclude(user__isnull=True, is_prediction=False)
        # By default, exclude predictions unless explicitly requested
        if not include_predicted_flag:
            qs = qs.filter(is_prediction=False)
        # By default, exclude true negatives unless explicitly requested via include
        if not include_true_negatives_flag:
            qs = qs.filter(true_negative=False)
        beatmap_id = params.get('beatmap_id')
        if beatmap_id:
            qs = qs.filter(beatmap__beatmap_id=str(beatmap_id))
        tag_name = params.get('tag')
        if tag_name:
            qs = qs.filter(tag__name__iexact=str(tag_name).strip().lower())
        return qs

    @action(detail=False, methods=['post'], url_path='toggle')
    def toggle_tags(self, request):
        """
        Apply/remove a tag for a beatmap.  
        If the beatmap isn’t in the DB yet, fetch it from the osu! API first.
        """
        # Signal active user interaction to pause background refreshers
        try:
            cache.incr('user_interaction_counter')
        except Exception:
            try:
                cache.set('user_interaction_counter', 1, timeout=60)
            except Exception:
                pass
        finally:
            try:
                # Short TTL pause guard in case counter fails
                cache.set('user_interaction_pause_until', timezone.now().timestamp() + 5, timeout=10)
            except Exception:
                pass
        serializer = TagApplicationToggleSerializer(
            data=request.data, context={'request': request}
        )

        if serializer.is_valid():
            return Response({'status': 'success', 'results': serializer.toggle_tags()})

        # ── handle ‘beatmap does not exist’ case ──────────────────────────
        errors = serializer.errors.get('beatmap_id', [])
        if len(serializer.errors) == 1 and 'Beatmap does not exist.' in errors:
            beatmap_id = request.data.get('beatmap_id')
            if not beatmap_id:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # fetch + save
            try:
                beatmap_data = api.beatmap(beatmap_id)
                if not beatmap_data:
                    raise ValueError(f'{beatmap_id} isn’t a valid beatmap ID.')

                with transaction.atomic():
                    beatmap, _ = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)

                    if hasattr(beatmap_data, '_beatmapset'):
                        bm_set = beatmap_data._beatmapset
                        beatmap.beatmapset_id = getattr(bm_set, 'id', beatmap.beatmapset_id)
                        beatmap.title = getattr(bm_set, 'title', beatmap.title)
                        beatmap.artist = getattr(bm_set, 'artist', beatmap.artist)
                        beatmap.creator = join_diff_creators(beatmap_data)
                        beatmap.cover_image_url = getattr(
                            getattr(bm_set, 'covers', {}),
                            'cover_2x',
                            beatmap.cover_image_url,
                        )

                    status_mapping = {
                        -2: 'Graveyard',
                        -1: 'WIP',
                        0: 'Pending',
                        1: 'Ranked',
                        2: 'Approved',
                        3: 'Qualified',
                        4: 'Loved',
                    }

                    beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
                    beatmap.total_length = getattr(
                        beatmap_data, 'total_length', beatmap.total_length
                    )
                    beatmap.bpm = getattr(beatmap_data, 'bpm', beatmap.bpm)
                    beatmap.cs = getattr(beatmap_data, 'cs', beatmap.cs)
                    beatmap.drain = getattr(beatmap_data, 'drain', beatmap.drain)
                    beatmap.accuracy = getattr(beatmap_data, 'accuracy', beatmap.accuracy)
                    beatmap.ar = getattr(beatmap_data, 'ar', beatmap.ar)
                    beatmap.difficulty_rating = getattr(
                        beatmap_data, 'difficulty_rating', beatmap.difficulty_rating
                    )
                    beatmap.mode = getattr(beatmap_data, 'mode', beatmap.mode)
                    beatmap.status = status_mapping.get(
                        beatmap_data.status.value, 'Unknown'
                    )
                    beatmap.save()

                # retry toggle after fetch
                serializer = TagApplicationToggleSerializer(
                    data=request.data, context={'request': request}
                )
                if serializer.is_valid():
                    return Response(
                        {'status': 'success', 'results': serializer.toggle_tags()}
                    )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            except Exception as exc:
                return Response({'beatmap_id': [str(exc)]}, status=400)

        # other validation errors
        # Decrement interaction counter on exit paths
        try:
            val = int(cache.decr('user_interaction_counter'))
            if val < 0:
                cache.set('user_interaction_counter', 0, timeout=60)
        except Exception:
            try:
                cache.set('user_interaction_counter', 0, timeout=60)
            except Exception:
                pass
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request, *args, **kwargs):
        """Slim payload when filtered by beatmap_id to avoid embedding full beatmap."""
        queryset = self.filter_queryset(self.get_queryset())
        is_filtered_by_bm = 'beatmap_id' in request.query_params
        if is_filtered_by_bm:
            beatmap_id = str(request.query_params.get('beatmap_id'))
            include_tokens = [s.strip() for s in (request.query_params.get('include') or '').split(',') if s.strip()]
            include_true_negatives_flag = ('true_negatives' in include_tokens) or ('negative_tags' in include_tokens)
            include_metadata_flag = ('metadata' in include_tokens)
            # Base lite serialization
            page = self.paginate_queryset(queryset)
            items = page or queryset
            data = TagApplicationLiteSerializer(items, many=True).data

            # Compute extras once per beatmap if requested
            need_counts = 'tag_counts' in include_tokens
            need_ts = 'tag_timestamps' in include_tokens
            counts_map = {}
            consensus_map = {}
            if need_counts or need_ts:
                base_qs = TagApplication.objects.filter(beatmap__beatmap_id=beatmap_id)
                # Always drop null-user non-predicted records
                base_qs = base_qs.exclude(user__isnull=True, is_prediction=False)
                # By default, exclude predictions unless explicitly requested
                include_predicted_flag = ('predicted_tags' in include_tokens) or (str(request.query_params.get('include_predicted', '0')).lower() in ['1', 'true', 'yes', 'on', 'include'])
                if not include_predicted_flag:
                    base_qs = base_qs.filter(is_prediction=False)
                # By default, exclude true negatives unless explicitly requested
                if not include_true_negatives_flag:
                    base_qs = base_qs.filter(true_negative=False)

                if need_counts:
                    counts = (
                        base_qs.values('tag_id')
                        .annotate(tag_count=Count('tag_id'))
                    )
                    counts_map = {row['tag_id']: row['tag_count'] for row in counts}

                if need_ts:
                    # Build per-tag user intervals and compute consensus intervals
                    try:
                        bm = Beatmap.objects.filter(beatmap_id=beatmap_id).first()
                        total_len = getattr(bm, 'total_length', 0) or 0
                    except Exception:
                        bm = None
                        total_len = 0
                    tmp = {}
                    for ta in base_qs.select_related('tag', 'user'):
                        tid = ta.tag_id
                        node = tmp.get(tid)
                        if node is None:
                            node = {'tag_id': tid, 'tag_name': getattr(ta.tag, 'name', ''), 'users': set(), 'user_to_intervals': {}}
                            tmp[tid] = node
                        if ta.user_id is not None and not getattr(ta, 'is_prediction', False):
                            node['users'].add(ta.user_id)
                            if isinstance(ta.timestamp, dict):
                                raw = (ta.timestamp or {}).get('intervals') or []
                                if raw:
                                    pairs = [(float(s), float(e)) for s, e in raw]
                                    lst = node['user_to_intervals'].setdefault(ta.user_id, [])
                                    lst.extend(pairs)
                    for tid, node in tmp.items():
                        per_user_lists = []
                        for _uid, ivs in node['user_to_intervals'].items():
                            merged = normalize_intervals(ivs, total_len)
                            if merged:
                                per_user_lists.append(merged)
                        intervals = consensus_intervals(per_user_lists, threshold_ratio=0.5, total_length_s=total_len)
                        consensus_map[tid] = intervals

            # Attach extras into each item's tag
            if need_counts or need_ts or include_metadata_flag:
                for entry in data:
                    tag = entry.get('tag') or {}
                    tid = tag.get('id')
                    if need_counts:
                        tag['count'] = counts_map.get(tid, 0)
                    if need_ts:
                        tag['consensus_intervals'] = consensus_map.get(tid, [])
                    if include_metadata_flag and tid:
                        # Attach category and parent associations
                        try:
                            t = Tag.objects.only('id', 'category').get(id=tid)
                            tag['category'] = getattr(t, 'category', 'other')
                            # Fetch parent ids via m2m through
                            parent_ids = list(t.parent_relations.values_list('parent_id', flat=True))
                            # Also include parent names for convenience
                            parents = list(Tag.objects.filter(id__in=parent_ids).values_list('name', flat=True)) if parent_ids else []
                            tag['parents'] = parents
                        except Exception:
                            tag['category'] = tag.get('category') or 'other'
                            tag['parents'] = []
                    entry['tag'] = tag

            # Attach per-user intervals when requested via user=me
            if request.user.is_authenticated and str(request.query_params.get('user')).strip().lower() == 'me':
                try:
                    bm = Beatmap.objects.filter(beatmap_id=beatmap_id).first()
                    total_len = getattr(bm, 'total_length', 0) or 0
                except Exception:
                    total_len = 0
                user_qs = TagApplication.objects.filter(beatmap__beatmap_id=beatmap_id, user=request.user).select_related('tag')
                if not include_true_negatives_flag:
                    user_qs = user_qs.filter(true_negative=False)
                user_map = {}
                for ta in user_qs:
                    intervals = []
                    if isinstance(ta.timestamp, dict):
                        raw = (ta.timestamp or {}).get('intervals') or []
                        intervals = normalize_intervals([(float(s), float(e)) for s, e in (raw or [])], total_len)
                    user_map[ta.tag_id] = intervals
                for entry in data:
                    tag = entry.get('tag') or {}
                    tid = tag.get('id')
                    if tid in user_map:
                        tag['user_intervals'] = user_map.get(tid) or []
                        entry['tag'] = tag

            if page is not None:
                return self.get_paginated_response(data)
            return Response(data)
        return super().list(request, *args, **kwargs)


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]


# ----------------------------- Admin Upload Endpoints ----------------------------- #

@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_upload_predictions(request):
    """Upload predicted tags in bulk (admin only).

    Accepted payloads:
      1) {"predictions": [{"beatmap_id": "123", "tag": "stream", "confidence": 0.91}, ...]}
      2) {"items": [{"beatmap_id": "123", "tag": "stream", "confidence": 0.91}, ...]}
      3) [{"beatmap_id": "123", "tag": "stream", "confidence": 0.91}, ...]
      4) [{"beatmap_id": "123", "tags": ["stream", {"tag":"alt","confidence":0.8}]}, ...]
    """
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    payload = request.data
    if isinstance(payload, dict) and 'predictions' in payload:
        items = payload.get('predictions') or []
    elif isinstance(payload, dict) and 'items' in payload:
        items = payload.get('items') or []
    elif isinstance(payload, list):
        items = payload
    else:
        return Response({'detail': 'Invalid payload.'}, status=400)

    created, updated, skipped, errors = 0, 0, 0, []

    def _ensure_beatmap(bm_id: str) -> Beatmap:
        bm_id = str(bm_id)
        beatmap, _ = Beatmap.objects.get_or_create(beatmap_id=bm_id)
        return beatmap

    for entry in items:
        try:
            if not isinstance(entry, dict):
                skipped += 1
                continue

            if 'tags' in entry and isinstance(entry['tags'], list):
                beatmap = _ensure_beatmap(entry.get('beatmap_id'))
                for tag_item in entry['tags']:
                    if isinstance(tag_item, str):
                        tag_name = tag_item.strip().lower()
                        confidence = None
                    elif isinstance(tag_item, dict):
                        tag_name = (tag_item.get('tag') or tag_item.get('name') or '').strip().lower()
                        confidence = tag_item.get('confidence')
                    else:
                        continue
                    if not tag_name:
                        continue
                    try:
                        tag, _ = Tag.get_or_create_for_mode(tag_name, beatmap.mode)
                    except ValueError as exc:
                        skipped += 1
                        errors.append(str(exc))
                        continue
                    # If a true negative exists for this beatmap+tag, ensure no predictions are kept
                    if TagApplication.objects.filter(tag=tag, beatmap=beatmap, true_negative=True).exists():
                        TagApplication.objects.filter(tag=tag, beatmap=beatmap, user__isnull=True, is_prediction=True).delete()
                        skipped += 1
                        continue
                    obj, created_row = TagApplication.objects.get_or_create(
                        tag=tag, beatmap=beatmap, user=None,
                        defaults={'is_prediction': True, 'prediction_confidence': confidence}
                    )
                    if created_row:
                        created += 1
                    else:
                        # Update confidence if provided
                        if confidence is not None:
                            obj.is_prediction = True
                            obj.prediction_confidence = confidence
                            obj.save(update_fields=['is_prediction', 'prediction_confidence'])
                            updated += 1
                        else:
                            skipped += 1
                continue

            beatmap_id = entry.get('beatmap_id')
            tag_name = (entry.get('tag') or entry.get('name') or '').strip().lower()
            confidence = entry.get('confidence')
            if not beatmap_id or not tag_name:
                skipped += 1
                continue

            beatmap = _ensure_beatmap(beatmap_id)
            try:
                tag, _ = Tag.get_or_create_for_mode(tag_name, beatmap.mode)
            except ValueError as exc:
                skipped += 1
                errors.append(str(exc))
                continue
            # Skip and delete predicted if a true negative exists
            if TagApplication.objects.filter(tag=tag, beatmap=beatmap, true_negative=True).exists():
                TagApplication.objects.filter(tag=tag, beatmap=beatmap, user__isnull=True, is_prediction=True).delete()
                skipped += 1
                continue
            obj, created_row = TagApplication.objects.get_or_create(
                tag=tag, beatmap=beatmap, user=None,
                defaults={'is_prediction': True, 'prediction_confidence': confidence}
            )
            if created_row:
                created += 1
            else:
                if confidence is not None:
                    obj.is_prediction = True
                    obj.prediction_confidence = confidence
                    obj.save(update_fields=['is_prediction', 'prediction_confidence'])
                    updated += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append(str(exc))

    return Response({'status': 'ok', 'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_upload_tag_applications(request):
    """Upload user tag applications in bulk (admin only).

    Payload options:
      - {"applications": [{"beatmap_id": "123", "tag": "stream", "osu_id": "4978940"}, ...]}
      - list of the same objects
      Fields to identify a user (one of): "osu_id", "user_id", "username".
      Optional: "created_at" (ISO 8601).
    """
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    payload = request.data
    if isinstance(payload, dict) and 'applications' in payload:
        items = payload.get('applications') or []
    elif isinstance(payload, list):
        items = payload
    else:
        return Response({'detail': 'Invalid payload.'}, status=400)

    created, skipped, errors = 0, 0, []

    for entry in items:
        try:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            beatmap_id = entry.get('beatmap_id')
            tag_name = (entry.get('tag') or '').strip().lower()
            if not beatmap_id or not tag_name:
                skipped += 1
                continue

            # Resolve or create user
            resolved_user = None
            osu_id = (entry.get('osu_id') or '').strip()
            username = (entry.get('username') or '').strip()
            user_id = entry.get('user_id')

            # 1) Prefer osu_id for deterministic identity; create if missing
            if osu_id:
                try:
                    profile = UserProfile.objects.get(osu_id=str(osu_id))
                    resolved_user = profile.user
                except UserProfile.DoesNotExist:
                    try:
                        from django.contrib.auth.models import User as DjangoUser
                        # Choose a username: provided username or fallback to osu-<id>
                        candidate = username or f'osu-{osu_id}'
                        base = candidate
                        suffix = 1
                        while True:
                            try:
                                u, created_user = DjangoUser.objects.get_or_create(username=candidate)
                                if not created_user and not username:
                                    # If fallback name exists but not tied to this osu_id, try next suffix
                                    candidate = f"{base}-{suffix}"
                                    suffix += 1
                                    continue
                                break
                            except Exception:
                                candidate = f"{base}-{suffix}"
                                suffix += 1
                        resolved_user = u
                        UserProfile.objects.create(user=resolved_user, osu_id=str(osu_id))
                    except Exception as create_exc:
                        errors.append(f"user_create_failed osu_id={osu_id}: {create_exc}")
                        resolved_user = None

            # 2) If still not resolved and username present, attempt lookup or create via osu API
            if not resolved_user and username:
                try:
                    from django.contrib.auth.models import User as DjangoUser
                    u = DjangoUser.objects.filter(username=username).first()
                    if u:
                        resolved_user = u
                    else:
                        # Try to resolve osu_id via Ossapi for profile creation
                        try:
                            from ossapi.enums import UserLookupKey
                            uid = None
                            try:
                                api_user = api.user(username, key=UserLookupKey.USERNAME)
                                uid = getattr(api_user, 'id', None)
                            except Exception:
                                uid = None
                            if uid:
                                u = DjangoUser.objects.create(username=username)
                                UserProfile.objects.create(user=u, osu_id=str(uid))
                                resolved_user = u
                            else:
                                # Create user without osu_id is not possible due to model constraint; skip
                                resolved_user = None
                        except Exception:
                            resolved_user = None
                except Exception:
                    resolved_user = None

            # 3) As a last resort, allow user_id mapping if an existing Django user exists
            if not resolved_user and user_id:
                try:
                    resolved_user = UserProfile._meta.model._meta.get_field('user').remote_field.model.objects.get(id=user_id)
                except Exception:
                    resolved_user = None

            if not resolved_user:
                skipped += 1
                continue

            beatmap, _ = Beatmap.objects.get_or_create(beatmap_id=str(beatmap_id))
            try:
                tag, _ = Tag.get_or_create_for_mode(tag_name, beatmap.mode)
            except ValueError as exc:
                skipped += 1
                errors.append(str(exc))
                continue

            obj, created_row = TagApplication.objects.get_or_create(
                tag=tag, beatmap=beatmap, user=resolved_user,
                defaults={'is_prediction': False}
            )
            if created_row:
                created += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(str(exc))

    return Response({'status': 'ok', 'created': created, 'skipped': skipped, 'errors': errors})


@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_upload_users(request):
    """Create or update users with profiles on the server (admin only).

    Accepted payloads:
      - {"users": [{"osu_id": "4978940", "username": "Name", "profile_pic_url": "..."}, ...]}
      - list of the same objects
    """
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    payload = request.data
    if isinstance(payload, dict) and 'users' in payload:
        items = payload.get('users') or []
    elif isinstance(payload, list):
        items = payload
    else:
        return Response({'detail': 'Invalid payload.'}, status=400)

    from django.contrib.auth.models import User as DjangoUser
    created, updated, skipped, errors = 0, 0, 0, []

    for entry in items:
        try:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            osu_id = str(entry.get('osu_id') or '').strip()
            username = (entry.get('username') or '').strip()
            profile_pic_url = (entry.get('profile_pic_url') or '').strip()
            if not osu_id or not username:
                skipped += 1
                continue

            # Prefer identity by osu_id
            profile = UserProfile.objects.filter(osu_id=osu_id).select_related('user').first()
            if profile:
                # Update username and profile pic if needed
                u = profile.user
                if u.username != username:
                    conflict = DjangoUser.objects.filter(username=username).exclude(pk=u.pk).first()
                    if conflict:
                        conflict.username = f"{conflict.username}__old__{conflict.id}"
                        conflict.save(update_fields=['username'])
                    u.username = username
                    u.save(update_fields=['username'])
                    updated += 1
                if profile.profile_pic_url != profile_pic_url:
                    profile.profile_pic_url = profile_pic_url
                    profile.save(update_fields=['profile_pic_url'])
                    updated += 1
                continue

            # No existing profile by osu_id → create or reuse username user
            user_obj = DjangoUser.objects.filter(username=username).first()
            if not user_obj:
                user_obj = DjangoUser.objects.create(username=username)
                created += 1
            else:
                updated += 1

            # Ensure profile exists with provided osu_id
            existing_profile = getattr(user_obj, 'userprofile', None)
            if existing_profile:
                chg = False
                if existing_profile.osu_id != osu_id:
                    existing_profile.osu_id = osu_id
                    chg = True
                if existing_profile.profile_pic_url != profile_pic_url:
                    existing_profile.profile_pic_url = profile_pic_url
                    chg = True
                if chg:
                    existing_profile.save(update_fields=['osu_id', 'profile_pic_url'])
            else:
                UserProfile.objects.create(user=user_obj, osu_id=osu_id, profile_pic_url=profile_pic_url)
                created += 1
        except Exception as exc:
            errors.append(str(exc))

    return Response({'status': 'ok', 'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_refresh_beatmaps(request):
    """Fetch and update beatmap metadata from osu! API for given IDs (admin only).

    Accepted payloads:
      - {"beatmap_ids": ["123", "456"]}
      - {"items": ["123", "456"]}
      - ["123", "456"]
      - {"items": [{"beatmap_id": "123"}, ...]}
    """
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    payload = request.data
    items = []
    if isinstance(payload, dict):
        if 'beatmap_ids' in payload and isinstance(payload['beatmap_ids'], list):
            items = payload['beatmap_ids']
        elif 'items' in payload and isinstance(payload['items'], list):
            items = payload['items']
        else:
            return Response({'detail': 'Invalid payload.'}, status=400)
    elif isinstance(payload, list):
        items = payload
    else:
        return Response({'detail': 'Invalid payload.'}, status=400)

    def _extract_id(it):
        if isinstance(it, dict):
            return str(it.get('beatmap_id') or it.get('id') or '').strip()
        return str(it).strip()

    processed = 0
    created = 0
    updated = 0
    skipped = 0
    errors = []

    status_mapping = {
        -2: 'Graveyard',
        -1: 'WIP',
        0: 'Pending',
        1: 'Ranked',
        2: 'Approved',
        3: 'Qualified',
        4: 'Loved',
    }

    for raw in items:
        bm_id = _extract_id(raw)
        if not bm_id or not bm_id.isdigit():
            skipped += 1
            continue
        processed += 1
        try:
            beatmap_data = api.beatmap(bm_id)
            if not beatmap_data:
                skipped += 1
                continue
            with transaction.atomic():
                beatmap, was_created = Beatmap.objects.get_or_create(beatmap_id=str(bm_id))
                created += 1 if was_created else 0

                if hasattr(beatmap_data, '_beatmapset'):
                    bm_set = beatmap_data._beatmapset
                    try:
                        beatmap.beatmapset_id = getattr(bm_set, 'id', beatmap.beatmapset_id)
                    except Exception:
                        pass
                    beatmap.title = getattr(bm_set, 'title', beatmap.title)
                    beatmap.artist = getattr(bm_set, 'artist', beatmap.artist)
                    # Preserve original set owner id/name if unset
                    set_owner_name = getattr(bm_set, 'creator', None)
                    set_owner_id = getattr(bm_set, 'user_id', None)
                    if not getattr(beatmap, 'original_creator', None):
                        beatmap.original_creator = set_owner_name
                    if not getattr(beatmap, 'original_creator_id', None):
                        try:
                            beatmap.original_creator_id = str(set_owner_id or '')
                        except Exception:
                            pass
                    beatmap.creator = join_diff_creators(beatmap_data)
                    try:
                        beatmap.cover_image_url = getattr(getattr(bm_set, 'covers', {}), 'cover_2x', beatmap.cover_image_url)
                    except Exception:
                        pass

                # Ensure listed owner fields are populated every refresh, unless manually overridden
                if not getattr(beatmap, 'listed_owner_is_manual_override', False):
                    try:
                        preferred_name = (beatmap.original_creator or '').strip() or (beatmap.creator or '').strip() or (set_owner_name or '')
                        preferred_id = (beatmap.original_creator_id or '') or (str(set_owner_id) if set_owner_id else '')
                        beatmap.listed_owner = preferred_name
                        beatmap.listed_owner_id = preferred_id or None
                    except Exception:
                        pass

                beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
                beatmap.total_length = getattr(beatmap_data, 'total_length', beatmap.total_length)
                beatmap.bpm = getattr(beatmap_data, 'bpm', beatmap.bpm)
                beatmap.cs = getattr(beatmap_data, 'cs', beatmap.cs)
                beatmap.drain = getattr(beatmap_data, 'drain', beatmap.drain)
                beatmap.accuracy = getattr(beatmap_data, 'accuracy', beatmap.accuracy)
                beatmap.ar = getattr(beatmap_data, 'ar', beatmap.ar)
                beatmap.difficulty_rating = getattr(beatmap_data, 'difficulty_rating', beatmap.difficulty_rating)
                # Map osu! API mode to canonical string used by search
                api_mode_value = getattr(beatmap_data, 'mode', beatmap.mode)
                beatmap.mode = GAME_MODE_MAPPING.get(str(api_mode_value), 'unknown')
                try:
                    beatmap.status = status_mapping.get(beatmap_data.status.value, getattr(beatmap, 'status', 'Unknown'))
                except Exception:
                    pass
                # Popularity fields
                try:
                    beatmap.playcount = getattr(beatmap_data, 'playcount', beatmap.playcount)
                except Exception:
                    pass
                try:
                    beatmap.favourite_count = getattr(getattr(beatmap_data, '_beatmapset', None), 'favourite_count', getattr(beatmap, 'favourite_count', 0))
                except Exception:
                    pass
                # Last updated if available
                try:
                    beatmap.last_updated = getattr(beatmap_data, 'last_updated', beatmap.last_updated)
                except Exception:
                    pass
                updated += 0 if was_created else 1
                beatmap.save()

            # Best-effort: compute and cache PP and timeseries so beatmap pages are complete
            try:
                from ..helpers.rosu_utils import (
                    get_or_compute_pp,
                    get_or_compute_modded_pps,
                    get_or_compute_timeseries,
                )
                get_or_compute_pp(beatmap)
                get_or_compute_modded_pps(beatmap)
                # 1-second window to match existing UI usage
                get_or_compute_timeseries(beatmap, window_seconds=1, mods=None)
            except Exception:
                pass

            # Best-effort: assign genres using external services
            try:
                from ..fetch_genre import fetch_genres, get_or_create_genres
                genres = fetch_genres(beatmap.artist or '', beatmap.title or '')
                if genres:
                    genre_objects = get_or_create_genres(genres)
                    beatmap.genres.set(genre_objects)
                else:
                    beatmap.genres.clear()
            except Exception:
                pass
        except Exception as exc:
            errors.append(f"{bm_id}: {exc}")
    return Response({'status': 'ok', 'processed': processed, 'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


# ----------------------------- Admin Predictions Maintenance ----------------------------- #

@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_flush_predictions(request):
    """Delete predicted tags for specific beatmap(s) (admin only).

    Accepted payloads:
      - {"beatmap_id": "123"}
      - {"beatmap_ids": ["123", "456"]}
      - {"items": ["123", {"beatmap_id": "456"}]}
    """
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    payload = request.data
    items = []
    if isinstance(payload, dict):
        if 'beatmap_id' in payload:
            items = [payload.get('beatmap_id')]
        elif 'beatmap_ids' in payload and isinstance(payload.get('beatmap_ids'), list):
            items = payload.get('beatmap_ids')
        elif 'items' in payload and isinstance(payload.get('items'), list):
            items = payload.get('items')
        else:
            return Response({'detail': 'Invalid payload.'}, status=400)
    elif isinstance(payload, list):
        items = payload
    else:
        return Response({'detail': 'Invalid payload.'}, status=400)

    def _extract_id(obj):
        if isinstance(obj, dict):
            return str(obj.get('beatmap_id') or obj.get('id') or '').strip()
        return str(obj).strip()

    ids = sorted({bm for bm in (_extract_id(x) for x in (items or [])) if bm})
    if not ids:
        return Response({'status': 'ok', 'deleted': 0})

    qs = TagApplication.objects.filter(beatmap__beatmap_id__in=ids, user__isnull=True, is_prediction=True)
    deleted_count, _ = qs.delete()
    return Response({'status': 'ok', 'deleted': deleted_count, 'beatmap_ids': ids})


@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def admin_flush_all_predictions(request):
    """Delete all predicted tags across all beatmaps (admin only)."""
    user = request.user
    if not getattr(user, 'is_staff', False):
        return Response({'detail': 'Admin privileges required.'}, status=403)

    qs = TagApplication.objects.filter(user__isnull=True, is_prediction=True)
    deleted_count, _ = qs.delete()
    return Response({'status': 'ok', 'deleted': deleted_count})


# ----------------------------- PP Calculation ----------------------------- #

@api_view(['POST'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([AllowAny])
def calculate_pp(request):
    """Calculate PP for a beatmap with custom parameters.
    
    Request body:
    {
        "beatmap_id": "123",
        "combo": 500,
        "accuracy": 98.5,
        "count_100": 10,
        "count_50": 5,
        "count_miss": 2,
        "mods": "HD,HR"  # Optional, comma-separated mods
    }
    
    Returns:
    {
        "pp": 123.45,
        "max_combo": 600,
        "mods": "HD,HR"
    }
    """
    try:
        beatmap_id = request.data.get('beatmap_id')
        if not beatmap_id:
            return Response({'error': 'beatmap_id is required'}, status=400)
        
        beatmap = get_object_or_404(Beatmap, beatmap_id=str(beatmap_id))
        
        # Get parameters with defaults
        combo = request.data.get('combo', beatmap.max_combo)
        accuracy = float(request.data.get('accuracy', 100.0))
        count_100 = int(request.data.get('count_100', 0))
        count_50 = int(request.data.get('count_50', 0))
        count_miss = int(request.data.get('count_miss', 0))
        mods_str = request.data.get('mods', '')
        
        # Parse mods string
        mods = None
        if mods_str:
            mods_list = [m.strip().upper() for m in mods_str.split(',') if m.strip()]
            # Filter valid mods and handle mutual exclusions
            valid_mods = []
            for mod in mods_list:
                if mod in ['HD', 'HR', 'DT', 'HT', 'EZ', 'FL']:
                    # Handle mutual exclusions
                    if mod == 'DT' and 'HT' in valid_mods:
                        valid_mods.remove('HT')
                    elif mod == 'HT' and 'DT' in valid_mods:
                        valid_mods.remove('DT')
                    elif mod == 'HR' and 'EZ' in valid_mods:
                        valid_mods.remove('EZ')
                    elif mod == 'EZ' and 'HR' in valid_mods:
                        valid_mods.remove('HR')
                    
                    if mod not in valid_mods:
                        valid_mods.append(mod)
            
            if valid_mods:
                mods = ''.join(valid_mods)
        
        # Calculate PP using rosu
        from ..helpers.rosu_utils import get_or_compute_pp
        
        # Calculate accuracy from hit counts if not provided directly
        if count_100 > 0 or count_50 > 0 or count_miss > 0:
            # This is a simplified accuracy calculation
            # In a real implementation, you'd need the total hit objects
            # For now, we'll use the provided accuracy value
            pass
        
        # Calculate PP with custom parameters
        pp_value = get_or_compute_pp(
            beatmap, 
            accuracy=accuracy, 
            misses=count_miss, 
            lazer=True,
            mods=mods
        )
        
        if pp_value is None:
            return Response({'error': 'Failed to calculate PP'}, status=500)
        
        return Response({
            'pp': round(pp_value, 2),
            'max_combo': beatmap.max_combo,
            'mods': mods or None,
            'combo': combo,
            'accuracy': accuracy,
            'count_100': count_100,
            'count_50': count_50,
            'count_miss': count_miss
        })
        
    except Exception as e:
        return Response({'error': str(e)}, status=500)
