from django.db import models
from django.conf import settings
from django.db.models import Count

class Beatmap(models.Model):
    beatmap_id = models.CharField(max_length=255, unique=True, db_index=True)
    beatmapset_id = models.CharField(max_length=100, blank=True, null=True)
    title = models.CharField(max_length=1000, null=False, blank=True)
    version = models.CharField(max_length=1000, null=False, blank=True)
    artist = models.CharField(max_length=1000, null=False, blank=True)
    creator = models.CharField(max_length=255, null=False, blank=True)
    cover_image_url = models.URLField(max_length=1000, null=True, blank=True)
    total_length = models.IntegerField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    cs = models.FloatField(null=True, blank=True)
    drain = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    ar = models.FloatField(null=True, blank=True)
    difficulty_rating = models.FloatField(null=True, blank=True)
    mode = models.CharField(max_length=100, null=False, blank=True)

    def get_weighted_tags(self):
        tags = self.tags.annotate(
            num_users=Count('tagapplication__user', distinct=True)
        ).order_by('-num_users')
        return tags


    def __str__(self):
        return self.beatmap_id or "Unknown id"

def get_default_user():
    # Try to get the user with the username 'The Emperor'
    try:
        return User.objects.get(username='The Emperor')
    except User.DoesNotExist:
        # If the user doesn't exist, fall back to the user with the osu_id '4978940'
        return UserProfile.objects.get(osu_id='4978940').user

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_default_user)
    osu_id = models.CharField(max_length=100, null=False, unique=True)
    profile_pic_url = models.URLField(max_length=1000, null=True, blank=True)

    def __str__(self):
        return self.user.username or "Unknown User"

from django.contrib.auth.models import User


def get_default_author():
    return User.objects.get_or_create(username='default_author')[0]

class Tag(models.Model):
    name = models.CharField(max_length=100, null=False, unique=True)
    description = models.CharField(max_length=255, unique=False, null=False, blank=True)
    description_author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tag_descriptions', default=get_default_author)
    beatmaps = models.ManyToManyField(Beatmap, related_name='tags', blank=True, through='TagApplication')

    def save(self, *args, **kwargs):
        self.name = self.name.strip().lower()
        super(Tag, self).save(*args, **kwargs)

    def __str__(self):
        return self.name




class TagApplication(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    beatmap = models.ForeignKey(Beatmap, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def agreed_by_others(self):
        return TagApplication.objects.filter(
            beatmap=self.beatmap,
            tag=self.tag
        ).exclude(
            user=self.user
        ).exists()

    class Meta:
        unique_together = ('tag', 'beatmap', 'user')

    def __str__(self):
        return f"{self.user.username} applied tag '{self.tag.name}' on {self.beatmap.beatmap_id}"

################ API ##################

from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
import hashlib

class CustomToken(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    user = models.ForeignKey(User, related_name='auth_tokens', on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    @classmethod
    def generate_key(cls):
        random_key = get_random_string(64)
        print(f"generate_key output: {random_key}")
        return random_key


    @classmethod
    def create_token(cls, user):
        raw_key = cls.generate_key()
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()

        # Debugging statements
        print(f"Generated raw_key: {raw_key}")
        print(f"Generated hashed_key: {hashed_key}")

        token = cls(key=hashed_key, user=user)
        token.save()
        return token, raw_key


class APIRequestLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.user.username} - {self.method} {self.path} at {self.timestamp}"