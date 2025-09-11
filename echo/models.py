from django.db import models
from django.conf import settings
from django.db.models import Count

class Genre(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class Beatmap(models.Model):
    beatmap_id = models.CharField(max_length=255, unique=True, db_index=True)
    beatmapset_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    title = models.CharField(max_length=1000, null=False, blank=True)
    version = models.CharField(max_length=1000, null=False, blank=True)
    artist = models.CharField(max_length=1000, null=False, blank=True)
    genres = models.ManyToManyField(Genre, blank=True)
    creator = models.CharField(max_length=255, null=False, blank=True, db_index=True)
    original_creator = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    original_creator_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    listed_owner = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    listed_owner_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    # True if `listed_owner` was set manually (by set owner or admin). Prevents API refresh from overwriting.
    listed_owner_is_manual_override = models.BooleanField(default=False, db_index=True)
    # True if the set owner has explicitly edited `listed_owner`. Used to block admin edits afterwards.
    listed_owner_edited_by_owner = models.BooleanField(default=False, db_index=True)
    cover_image_url = models.URLField(max_length=1000, null=True, blank=True)
    total_length = models.IntegerField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    cs = models.FloatField(null=True, blank=True)
    drain = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    ar = models.FloatField(null=True, blank=True)
    difficulty_rating = models.FloatField(null=True, blank=True, db_index=True)
    mode = models.CharField(max_length=100, null=False, blank=True, db_index=True)
    status = models.CharField(max_length=32, null=False, blank=True, db_index=True)
    playcount = models.IntegerField(null=True, blank=True, db_index=True)
    favourite_count = models.IntegerField(null=True, blank=True, db_index=True)
    last_updated = models.DateTimeField(null=True, blank=True, db_index=True)
    pp_nomod = models.FloatField(null=True, blank=True, db_index=True)
    pp_hd = models.FloatField(null=True, blank=True, db_index=True)
    pp_hr = models.FloatField(null=True, blank=True, db_index=True)
    pp_dt = models.FloatField(null=True, blank=True, db_index=True)
    pp_ht = models.FloatField(null=True, blank=True, db_index=True)
    pp_ez = models.FloatField(null=True, blank=True, db_index=True)
    pp_fl = models.FloatField(null=True, blank=True, db_index=True)
    max_combo = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            # Composite indexes for common query patterns
            models.Index(fields=['mode', 'difficulty_rating']),
            models.Index(fields=['status', 'difficulty_rating']),
            models.Index(fields=['creator', 'status']),
            models.Index(fields=['playcount', 'difficulty_rating']),
            models.Index(fields=['favourite_count', 'difficulty_rating']),
            models.Index(fields=['last_updated', 'status']),
            # Text search optimization
            models.Index(fields=['title', 'artist']),
            models.Index(fields=['artist', 'title']),
        ]

    def get_weighted_tags(self):
        tags = self.tags.annotate(
            num_users=Count('tagapplication__user', distinct=True)
        ).order_by('-num_users')
        return tags

    def __str__(self):
        return self.beatmap_id or "Unknown id"



def get_default_user():
    return UserProfile.objects.get(osu_id='4978940').user


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_default_user)
    osu_id = models.CharField(max_length=100, null=False, unique=True, db_index=True)
    profile_pic_url = models.URLField(max_length=1000, null=True, blank=True)
    banned = models.BooleanField(default=False, db_index=True)
    ban_reason = models.CharField(max_length=255, unique=False, null=False, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['banned', 'osu_id']),
        ]

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
    upvotes = models.PositiveIntegerField(default=0, db_index=True)
    downvotes = models.PositiveIntegerField(default=0, db_index=True)
    is_locked = models.BooleanField(default=False, db_index=True)
    is_recommended = models.BooleanField(default=False, db_index=True)
    # Tag categorization
    CATEGORY_MAPPING_GENRE = 'mapping_genre'
    CATEGORY_PATTERN_TYPE = 'pattern_type'
    CATEGORY_METADATA = 'metadata'
    CATEGORY_OTHER = 'other'
    CATEGORY_CHOICES = [
        (CATEGORY_MAPPING_GENRE, 'Mapping Genre'),
        (CATEGORY_PATTERN_TYPE, 'Pattern Type'),
        (CATEGORY_METADATA, 'Metadata'),
        (CATEGORY_OTHER, 'Other'),
    ]
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER, db_index=True)
    # Directed hierarchy: a tag can have multiple parent tags; children are derived via related_name
    parents = models.ManyToManyField(
        'self',
        symmetrical=False,
        through='TagRelation',
        through_fields=('child', 'parent'),
        related_name='children',
        blank=True
    )

    class Meta:
        indexes = [
            # Vote-based sorting and filtering
            models.Index(fields=['upvotes', 'downvotes']),
            models.Index(fields=['is_recommended', 'upvotes']),
            models.Index(fields=['is_locked', 'upvotes']),
            # Text search optimization
            models.Index(fields=['name', 'is_recommended']),
            models.Index(fields=['category']),
        ]

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
    date_written = models.DateTimeField(auto_now_add=True, db_index=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)
    

    class Meta:
        ordering = ['-date_written']
        indexes = [
            models.Index(fields=['tag', 'date_written']),
            models.Index(fields=['author', 'date_written']),
        ]

    def __str__(self):
        return f"{self.tag.name} - {self.date_written.strftime('%Y-%m-%d %H:%M:%S')} by {self.author}"


class TagRelation(models.Model):
    """Directed association between tags to support hierarchy (parent -> child)."""
    parent = models.ForeignKey('Tag', on_delete=models.CASCADE, related_name='child_relations')
    child = models.ForeignKey('Tag', on_delete=models.CASCADE, related_name='parent_relations')

    class Meta:
        unique_together = ('parent', 'child')
        indexes = [
            models.Index(fields=['parent', 'child']),
            models.Index(fields=['child', 'parent']),
        ]

    def __str__(self):
        try:
            return f"{self.parent.name} -> {self.child.name}"
        except Exception:
            return "<tag relation>"

class Vote(models.Model):
    UPVOTE = 'upvote'
    DOWNVOTE = 'downvote'
    VOTE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='votes')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='votes')
    vote_type = models.CharField(max_length=10, choices=VOTE_CHOICES, db_index=True)  # Corrected max_length
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = ('user', 'tag')  # Ensures a user can vote only once per tag
        indexes = [
            models.Index(fields=['user', 'tag']),
            models.Index(fields=['tag', 'vote_type']),
            models.Index(fields=['timestamp', 'vote_type']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} {self.vote_type}d '{self.tag.name}'"


class TagApplication(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    beatmap = models.ForeignKey(Beatmap, on_delete=models.CASCADE)
    timestamp = models.JSONField(default=dict, blank=True, null=True)
    is_prediction = models.BooleanField(default=False, help_text="Indicates if tag is predicted for this beatmap", db_index=True)
    true_negative = models.BooleanField(default=False, help_text="Indicates this tag is an explicit true negative for this beatmap", db_index=True)
    prediction_confidence = models.FloatField(default=0.0, blank=True, null=True, help_text="Confidence level of the prediction", db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    def agreed_by_others(self):
        return TagApplication.objects.filter(
            beatmap=self.beatmap,
            tag=self.tag
        ).exclude(
            user=self.user
        ).exists()

    class Meta:
        unique_together = ('tag', 'beatmap', 'user', 'true_negative', 'is_prediction')
        indexes = [
            # Existing indexes
            models.Index(fields=['beatmap', 'tag']),
            models.Index(fields=['user', 'beatmap']),
            models.Index(fields=['tag', 'user']),
            models.Index(fields=['is_prediction']),
            models.Index(fields=['true_negative']),
            # Additional performance indexes
            models.Index(fields=['created_at', 'is_prediction']),
            models.Index(fields=['created_at', 'true_negative']),
            models.Index(fields=['beatmap', 'is_prediction']),
            models.Index(fields=['beatmap', 'true_negative']),
            models.Index(fields=['tag', 'is_prediction']),
            models.Index(fields=['tag', 'true_negative']),
            models.Index(fields=['prediction_confidence', 'is_prediction']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['beatmap', 'created_at']),
        ]
        
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
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created']),
        ]

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
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    method = models.CharField(max_length=10, db_index=True)
    path = models.CharField(max_length=255, db_index=True)
    status_code = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['timestamp', 'method']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['path', 'timestamp']),
            models.Index(fields=['method', 'path']),
        ]

    def __str__(self):
        username = getattr(self.user, 'username', 'anonymous')
        return f"{username} - {self.method} {self.path} at {self.timestamp}"


# ----------------------------- User Settings ----------------------------- #

class UserSettings(models.Model):
    """Per-user UI preferences and feature flags.

    Currently stores the preferred tag category display mode for tag cards.
    """
    DISPLAY_NONE = 'none'
    DISPLAY_COLOR = 'color'
    DISPLAY_LISTS = 'lists'
    DISPLAY_CHOICES = [
        (DISPLAY_NONE, 'No Categories'),
        (DISPLAY_COLOR, 'Color Coding'),
        (DISPLAY_LISTS, 'Separate Lists'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='settings')
    tag_category_display = models.CharField(max_length=16, choices=DISPLAY_CHOICES, default=DISPLAY_NONE, db_index=True)
    # Feature flag: when enabled, tags are visually grouped by parent relations on cards
    group_related_tags = models.BooleanField(default=False, db_index=True)

    # ---------------------- Tag Card Visibility Preferences ---------------------- #
    # Major stats
    show_star_rating = models.BooleanField(default=True, db_index=True)
    show_status = models.BooleanField(default=True, db_index=True)
    # Basic stats
    show_cs = models.BooleanField(default=True, db_index=True)
    show_hp = models.BooleanField(default=True, db_index=True)
    show_od = models.BooleanField(default=True, db_index=True)
    show_ar = models.BooleanField(default=True, db_index=True)
    # Minor stats
    show_bpm = models.BooleanField(default=True, db_index=True)
    show_length = models.BooleanField(default=True, db_index=True)
    show_year = models.BooleanField(default=True, db_index=True)
    show_playcount = models.BooleanField(default=True, db_index=True)
    show_favourites = models.BooleanField(default=True, db_index=True)
    # Genres section
    show_genres = models.BooleanField(default=True, db_index=True)
    # PP pills (mods)
    show_pp_nm = models.BooleanField(default=True, db_index=True)
    show_pp_hd = models.BooleanField(default=True, db_index=True)
    show_pp_hr = models.BooleanField(default=True, db_index=True)
    show_pp_dt = models.BooleanField(default=True, db_index=True)
    show_pp_ht = models.BooleanField(default=True, db_index=True)
    show_pp_ez = models.BooleanField(default=True, db_index=True)
    show_pp_fl = models.BooleanField(default=True, db_index=True)
    # PP calculator
    show_pp_calculator = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['tag_category_display']),
            models.Index(fields=['user', 'tag_category_display']),
        ]

    def __str__(self):
        try:
            uname = self.user.username
        except Exception:
            uname = 'unknown'
        return f"Settings({uname}): tag_display={self.tag_category_display}"