from rest_framework import serializers
from .models import TagApplication, Tag, Beatmap, UserProfile
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username']

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']

class BeatmapSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Beatmap
        fields = ['id', 'beatmap_id', 'title', 'artist', 'tags']

class TagApplicationSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    tag = TagSerializer(read_only=True)
    beatmap = BeatmapSerializer(read_only=True)

    class Meta:
        model = TagApplication
        fields = ['id', 'user', 'tag', 'beatmap', 'created_at']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True) 

    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'osu_id', 'profile_pic_url']


########### WRITE API ###########

from better_profanity import profanity
import re

# Define the allowed tag pattern
ALLOWED_TAG_PATTERN = re.compile(r'^[A-Za-z0-9 _\-\/]{1,25}$')

class TagApplicationToggleSerializer(serializers.Serializer):
    beatmap_id = serializers.CharField(max_length=255)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=25),
        allow_empty=False
    )

    def validate_beatmap_id(self, value):
        if not Beatmap.objects.filter(beatmap_id=value).exists():
            raise serializers.ValidationError("Beatmap does not exist.")
        return value

    def validate_tags(self, value):
        if not value:
            raise serializers.ValidationError("At least one tag must be provided.")
        cleaned_tags = []
        for tag in value:
            tag_clean = tag.strip().lower()
            if not ALLOWED_TAG_PATTERN.match(tag_clean):
                raise serializers.ValidationError(
                    "Tags must be 1-25 characters long and can only contain letters, numbers, spaces, hyphens, and underscores."
                )
            if profanity.contains_profanity(tag_clean):
                raise serializers.ValidationError("Tags cannot contain inappropriate language.")
            cleaned_tags.append(tag_clean)
        return cleaned_tags

    def toggle_tags(self):
        """
        Toggle tags for a beatmap. Applies the tag if not already applied by the user,
        or removes it if already applied.
        """
        user = self.context['request'].user
        beatmap_id = self.validated_data['beatmap_id']
        tags = self.validated_data['tags']

        try:
            beatmap = Beatmap.objects.get(beatmap_id=beatmap_id)
        except Beatmap.DoesNotExist:
            # This should be caught by validate_beatmap_id, but added for safety
            raise serializers.ValidationError("Beatmap does not exist.")

        results = []

        for tag_name in tags:
            try:
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                tag_application, created = TagApplication.objects.get_or_create(
                    tag=tag,
                    beatmap=beatmap,
                    user=user
                )
                if created:
                    # Tag was applied
                    results.append({
                        "tag": tag.name,
                        "action": "applied"
                    })
                else:
                    # Tag was already applied; remove it
                    tag_application.delete()
                    # Delete the tag if no more applications exist
                    if not TagApplication.objects.filter(tag=tag).exists():
                        tag.delete()
                    results.append({
                        "tag": tag.name,
                        "action": "removed"
                    })
            except Exception as e:
                results.append({
                    "tag": tag_name,
                    "action": "error",
                    "message": str(e)
                })

        return results