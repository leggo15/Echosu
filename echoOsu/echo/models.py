from django.db import models
from django.conf import settings

class Beatmap(models.Model):
    beatmap_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=1000, null=True, blank=True)
    version = models.CharField(max_length=1000, null=True, blank=True)
    artist = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.CharField(max_length=255, null=True, blank=True)
    cover_image_url = models.URLField(max_length=1000, null=True, blank=True)
    total_length = models.IntegerField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    cs = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    ar = models.FloatField(null=True, blank=True)
    difficulty_rating = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.beatmap_id or "Unknown id"


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    beatmaps = models.ManyToManyField(Beatmap, related_name='tags', blank=True, through='TagApplication')

    def __str__(self):
        return self.name


class TagApplication(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    beatmap = models.ForeignKey(Beatmap, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tag', 'beatmap', 'user')

    def __str__(self):
        return f"{self.user.username} applied tag '{self.tag.name}' on {self.beatmap.beatmap_id}"


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    osu_id = models.CharField(max_length=100, unique=True)
    profile_pic_url = models.URLField(max_length=1000, null=True, blank=True)

    def __str__(self):
        return self.user.username or "Unknown User"