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
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
    TagApplicationToggleSerializer,
    TagSerializer,
    UserProfileSerializer,
)
from .auth import api                         # shared Ossapi instance
from .beatmap import join_diff_creators       # helper
# --------------------------------------------------------------------- #


# ----------------------------- Helper endpoints ----------------------------- #

@api_view(['GET'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def tags_for_beatmaps(request, beatmap_id=None):
    if beatmap_id:
        beatmaps = Beatmap.objects.filter(beatmap_id=beatmap_id)
        if not beatmaps.exists():
            return Response({'detail': 'Beatmap not found.'}, status=404)
    else:
        batch_size = int(request.GET.get('batch_size', 500))
        offset = int(request.GET.get('offset', 0))
        beatmaps = (
            Beatmap.objects.annotate(tag_count=Count('tagapplication'))
            .filter(tag_count__gt=0)
            .order_by('id')[offset : offset + batch_size]
        )
        if not beatmaps.exists():
            return Response({'detail': 'No beatmaps found.'}, status=404)

    result = []
    for beatmap in beatmaps:
        # Exclude predicted and non-user applications from export
        tag_counts = (
            TagApplication.objects
            .filter(beatmap=beatmap, is_prediction=False)
            .exclude(user__isnull=True)
            .values('tag__name')
            .annotate(tag_count=Count('tag'))
            .order_by('-tag_count')
        )
        tags_data = [{'tag': t['tag__name'], 'count': t['tag_count']} for t in tag_counts]
        result.append(
            {
                'beatmap_id': beatmap.beatmap_id,
                'title': beatmap.title,
                'artist': beatmap.artist,
                'tags': tags_data,
            }
        )
    return Response(result)


# ----------------------------- Token helper ----------------------------- #

@login_required
def generate_token(request):
    if request.method == 'POST':
        CustomToken.objects.filter(user=request.user).delete()
        token = CustomToken.objects.create(user=request.user)
        return render(request, 'settings.html', {'token_key': token.key})

    return redirect('settings')


# ----------------------------- API ViewSets ----------------------------- #

class BeatmapViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Beatmap.objects.all()
    serializer_class = BeatmapSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

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


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]


class TagApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TagApplication.objects.all()
    serializer_class = TagApplicationSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        include_predicted = str(params.get('include_predicted', '0')).lower() in ['1', 'true', 'yes', 'on', 'include']
        if not include_predicted:
            qs = qs.filter(is_prediction=False).exclude(user__isnull=True)
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
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
                    tag, _ = Tag.objects.get_or_create(name=tag_name)
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
            tag, _ = Tag.objects.get_or_create(name=tag_name)
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

            # Resolve user
            resolved_user = None
            osu_id = (entry.get('osu_id') or '').strip()
            username = (entry.get('username') or '').strip()
            user_id = entry.get('user_id')
            if osu_id:
                try:
                    profile = UserProfile.objects.get(osu_id=str(osu_id))
                    resolved_user = profile.user
                except UserProfile.DoesNotExist:
                    resolved_user = None
            if not resolved_user and user_id:
                try:
                    resolved_user = UserProfile._meta.model._meta.get_field('user').remote_field.model.objects.get(id=user_id)
                except Exception:
                    resolved_user = None
            if not resolved_user and username:
                try:
                    from django.contrib.auth.models import User as DjangoUser
                    resolved_user = DjangoUser.objects.get(username=username)
                except Exception:
                    resolved_user = None

            if not resolved_user:
                skipped += 1
                continue

            beatmap, _ = Beatmap.objects.get_or_create(beatmap_id=str(beatmap_id))
            tag, _ = Tag.objects.get_or_create(name=tag_name)

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
