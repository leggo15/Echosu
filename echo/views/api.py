# echosu/views/api.py

# Django imports
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404

# REST framework imports
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# Local application imports
from ..models import Beatmap, Tag, TagApplication, UserProfile
from ..serializers import (
    BeatmapSerializer, TagSerializer, TagApplicationSerializer, 
    UserProfileSerializer, TagApplicationToggleSerializer
)
# Assuming a custom token auth backend exists
from ..authentication import CustomTokenAuthentication 
from .auth import api # Shared Ossapi instance
from .beatmap import join_diff_creators, GAME_MODE_MAPPING # Helpers



# ----------------------------- API Views ----------------------------- #

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count
from ..models import Beatmap, Tag, TagApplication, UserProfile
from ..serializers import BeatmapSerializer, TagSerializer, TagApplicationSerializer, UserProfileSerializer, TagApplicationToggleSerializer
from echo.authentication import CustomTokenAuthentication

@api_view(['GET'])
@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated])
def tags_for_beatmaps(request, beatmap_id=None):
    if beatmap_id:
        beatmaps = Beatmap.objects.filter(beatmap_id=beatmap_id)
        if not beatmaps.exists():
            return Response({"detail": "Beatmap not found."}, status=404)
    else:
        batch_size = int(request.GET.get('batch_size', 500))
        offset = int(request.GET.get('offset', 0))
        beatmaps = Beatmap.objects.annotate(tag_count=Count('tagapplication')).filter(
            tag_count__gt=0
        ).order_by('id')[offset:offset + batch_size]
        if not beatmaps.exists():
            return Response({"detail": "No beatmaps found."}, status=404)

    result = []
    for beatmap in beatmaps:
        tag_counts = TagApplication.objects.filter(beatmap=beatmap).values('tag__name').annotate(
            tag_count=Count('tag')
        ).order_by('-tag_count')
        tags_data = [{'tag': item['tag__name'], 'count': item['tag_count']} for item in tag_counts]
        result.append({
            'beatmap_id': beatmap.beatmap_id,
            'title': beatmap.title,
            'artist': beatmap.artist,
            'tags': tags_data
        })

    return Response(result)


from ..models import CustomToken
from django.contrib.auth.decorators import login_required

@login_required
def generate_token(request):
    if request.method == 'POST':
        # Delete existing tokens
        CustomToken.objects.filter(user=request.user).delete()
        # Create new token
        token = CustomToken.objects.create(user=request.user)
        # Store the token key temporarily to display to the user
        token_key = token.key
        messages.success(request, 'Your API token has been generated.')
        return render(request, 'settings.html', {'token_key': token_key})
    else:
        return redirect('settings')

# ------------------------------------------------------------------------ #

# ----------------------------- API ViewSets ----------------------------- #


class BeatmapViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Beatmap.objects.all()
    serializer_class = BeatmapSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='filtered')
    def filtered(self, request):
        query = request.query_params.get('query', None)
        if query:
            # Filter beatmaps based on title, artist, or tag names
            beatmaps = Beatmap.objects.filter(
                Q(title__icontains=query) |
                Q(artist__icontains=query) |
                Q(tags__name__icontains=query)
            ).distinct()
            serializer = self.get_serializer(beatmaps, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"detail": "Query parameter 'query' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )


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
        Toggle tags for a beatmap. Applies the tag if not already applied by the user,
        or removes it if already applied. If the beatmap does not exist in the database,
        fetch it from the osu! API and add it to the database before proceeding.
        """
        serializer = TagApplicationToggleSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            results = serializer.toggle_tags()
            return Response({
                "status": "success",
                "results": results
            }, status=status.HTTP_200_OK)
        else:
            # Check if the only error is 'beatmap_id' does not exist
            beatmap_errors = serializer.errors.get('beatmap_id', [])
            if len(serializer.errors) == 1 and "Beatmap does not exist." in beatmap_errors:
                beatmap_id = request.data.get('beatmap_id')
                if not beatmap_id:
                    # beatmap_id is missing or invalid
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    # Fetch beatmap data from osu! API
                    beatmap_data = api.beatmap(beatmap_id)
                    if not beatmap_data:
                        raise ValueError(f"{beatmap_id} isn't a valid beatmap ID.")
                    
                    # Start a transaction to ensure atomicity
                    with transaction.atomic():
                        # Get or create the beatmap object in the database
                        beatmap, created = Beatmap.objects.get_or_create(beatmap_id=beatmap_id)
                        
                        # Update beatmap attributes from the API data
                        # This logic mirrors your existing 'home' view
                        if hasattr(beatmap_data, '_beatmapset'):
                            beatmapset = beatmap_data._beatmapset
                            beatmap.beatmapset_id = getattr(beatmapset, 'id', beatmap.beatmapset_id)
                            beatmap.title = getattr(beatmapset, 'title', beatmap.title)
                            beatmap.artist = getattr(beatmapset, 'artist', beatmap.artist)
                            beatmap.creator = join_diff_creators(beatmap_data)
                            beatmap.cover_image_url = getattr(
                                getattr(beatmapset, 'covers', {}),
                                'cover_2x',
                                beatmap.cover_image_url
                            )
                        
                        status_mapping = {
                            -2: "Graveyard",
                            -1: "WIP",
                            0: "Pending",
                            1: "Ranked",
                            2: "Approved",
                            3: "Qualified",
                            4: "Loved"
                        }
                        
                        # Update other beatmap attributes
                        beatmap.version = getattr(beatmap_data, 'version', beatmap.version)
                        beatmap.total_length = getattr(beatmap_data, 'total_length', beatmap.total_length)
                        beatmap.bpm = getattr(beatmap_data, 'bpm', beatmap.bpm)
                        beatmap.cs = getattr(beatmap_data, 'cs', beatmap.cs)
                        beatmap.drain = getattr(beatmap_data, 'drain', beatmap.drain)
                        beatmap.accuracy = getattr(beatmap_data, 'accuracy', beatmap.accuracy)
                        beatmap.ar = getattr(beatmap_data, 'ar', beatmap.ar)
                        beatmap.difficulty_rating = getattr(beatmap_data, 'difficulty_rating', beatmap.difficulty_rating)
                        beatmap.mode = getattr(beatmap_data, 'mode', beatmap.mode)
                        beatmap.status = status_mapping.get(beatmap_data.status.value, "Unknown")
                        
                        # Save the updated beatmap to the database
                        beatmap.save()
                    
                    # After successfully fetching and saving the beatmap, re-validate the serializer
                    serializer = TagApplicationToggleSerializer(data=request.data, context={'request': request})
                    if serializer.is_valid():
                        results = serializer.toggle_tags()
                        return Response({
                            "status": "success",
                            "results": results
                        }, status=status.HTTP_200_OK)
                    else:
                        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
                except Exception as e:
                    # Log the error as needed
                    return Response({
                        "beatmap_id": [str(e)]
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # Return other validation errors
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]