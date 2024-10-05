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
    class Meta:
        model = Beatmap
        fields = ['id', 'beatmap_id', 'title', 'artist']

class TagApplicationSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    tag = TagSerializer(read_only=True)
    beatmap = BeatmapSerializer(read_only=True)

    class Meta:
        model = TagApplication
        fields = ['id', 'user', 'tag', 'beatmap', 'created_at']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)  # Include related user details if needed

    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'osu_id', 'profile_pic_url']
