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
        tag_counts = (
            TagApplication.objects.filter(beatmap=beatmap)
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
