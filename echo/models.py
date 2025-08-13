from django.db import models
from django.conf import settings
from django.db.models import Count

class Genre(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class Beatmap(models.Model):
    beatmap_id = models.CharField(max_length=255, unique=True, db_index=True)
    beatmapset_id = models.CharField(max_length=100, blank=True, null=True)
    title = models.CharField(max_length=1000, null=False, blank=True)
    version = models.CharField(max_length=1000, null=False, blank=True)
    artist = models.CharField(max_length=1000, null=False, blank=True)
    genres = models.ManyToManyField(Genre, blank=True)
    creator = models.CharField(max_length=255, null=False, blank=True)
    original_creator = models.CharField(max_length=255, null=True, blank=True)
    original_creator_id = models.CharField(max_length=50, null=True, blank=True)
    listed_owner = models.CharField(max_length=255, null=True, blank=True)
    listed_owner_id = models.CharField(max_length=50, null=True, blank=True)
    cover_image_url = models.URLField(max_length=1000, null=True, blank=True)
    total_length = models.IntegerField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    cs = models.FloatField(null=True, blank=True)
    drain = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    ar = models.FloatField(null=True, blank=True)
    difficulty_rating = models.FloatField(null=True, blank=True)
    mode = models.CharField(max_length=100, null=False, blank=True)
    status = models.CharField(max_length=32, null=False, blank=True)
    playcount = models.IntegerField(null=True, blank=True)
    favourite_count = models.IntegerField(null=True, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    rosu_timeseries = models.JSONField(default=dict, blank=True, null=True)
    pp_nomod = models.FloatField(null=True, blank=True)
    pp_hd = models.FloatField(null=True, blank=True)
    pp_hr = models.FloatField(null=True, blank=True)
    pp_dt = models.FloatField(null=True, blank=True)
    pp_ht = models.FloatField(null=True, blank=True)
    pp_ez = models.FloatField(null=True, blank=True)
    pp_fl = models.FloatField(null=True, blank=True)

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
    banned = models.BooleanField(default=False)
    ban_reason = models.CharField(max_length=255, unique=False, null=False, blank=True)

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
    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    is_locked = models.BooleanField(default=False)
    is_recommended = models.BooleanField(default=False)

    def vote_score(self):
        return self.upvotes - self.downvotes

    def save(self, *args, **kwargs):
        # Pop 'user' from kwargs if present
        user = kwargs.pop('user', None)

        # Detect if the description has changed
        if self.pk:
            previous = Tag.objects.get(pk=self.pk)
            if previous.description != self.description:
                # Reset votes and lock status
                self.upvotes = 0
                self.downvotes = 0
                self.is_locked = False
                # Delete all existing votes for this tag
                self.votes.all().delete()
                # Create a new description history entry with the new author
                TagDescriptionHistory.objects.create(
                    tag=self,
                    description=previous.description,
                    author=user if user else previous.description_author
                )
        self.name = self.name.strip().lower()
        super(Tag, self).save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class TagDescriptionHistory(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='description_histories')
    description = models.CharField(max_length=255)
    date_written = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    

    class Meta:
        ordering = ['-date_written']

    def __str__(self):
        return f"{self.tag.name} - {self.date_written.strftime('%Y-%m-%d %H:%M:%S')} by {self.author}"


class Vote(models.Model):
    UPVOTE = 'upvote'
    DOWNVOTE = 'downvote'
    VOTE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='votes')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='votes')
    vote_type = models.CharField(max_length=10, choices=VOTE_CHOICES)  # Corrected max_length
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'tag')  # Ensures a user can vote only once per tag
        indexes = [
            models.Index(fields=['user', 'tag']),
        ]

    def __str__(self):
        return f"{self.user.username} {self.vote_type}d '{self.tag.name}'"


class TagApplication(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    beatmap = models.ForeignKey(Beatmap, on_delete=models.CASCADE)
    timestamp = models.JSONField(default=dict, blank=True, null=True)
    is_prediction = models.BooleanField(default=False, help_text="Indicates if tag is predicted for this beatmap")
    prediction_confidence = models.FloatField(default=0.0, blank=True, null=True, help_text="Confidence level of the prediction")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

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
        user_name = getattr(getattr(self, 'user', None), 'username', 'anonymous')
        try:
            tag_name = getattr(getattr(self, 'tag', None), 'name', '?')
        except Exception:
            tag_name = '?'
        bm_id = getattr(getattr(self, 'beatmap', None), 'beatmap_id', '?')
        return f"{user_name} applied tag '{tag_name}' on {bm_id}"


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
        return random_key


    @classmethod
    def create_token(cls, user):
        raw_key = cls.generate_key()
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()

        token = cls(key=hashed_key, user=user)
        token.save()
        return token, raw_key


class APIRequestLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.user.username} - {self.method} {self.path} at {self.timestamp}"