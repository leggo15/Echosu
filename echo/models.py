from django.db import models
from django.conf import settings
from django.db.models import Count, F, FloatField
from django.db.models.functions import Coalesce

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


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    osu_id = models.CharField(max_length=100, null=False, unique=True)
    profile_pic_url = models.URLField(max_length=1000, null=True, blank=True)

    def __str__(self):
        return self.user.username or "Unknown User"


class Tag(models.Model):
    name = models.CharField(max_length=100, null=False, unique=True)
    description = models.CharField(max_length=255, unique=False, null=False, blank=True)
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


from django.db import models
from rest_framework_api_key.models import AbstractAPIKey
from django.contrib.auth.models import User

class CustomAPIKey(AbstractAPIKey):
    key_name = models.CharField(max_length=255, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')

    class Meta(AbstractAPIKey.Meta):
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
