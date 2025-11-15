from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.test.client import RequestFactory
import time
import threading
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from .models import Beatmap, UserProfile, Tag, TagApplication, TagDescriptionHistory, TagRelation
from .models import APIRequestLog, AnalyticsSearchEvent, AnalyticsClickEvent
from .views.beatmap import update_beatmap_info
from .views.api import admin_flush_all_predictions

@admin.register(Beatmap)
class BeatmapAdmin(admin.ModelAdmin):
    list_display = ('beatmap_id', 'title', 'artist', 'creator', 'status')
    search_fields = ('beatmap_id', 'title', 'artist', 'creator')
    change_list_template = 'admin/echo/beatmap/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('refresh-all/', self.admin_site.admin_view(self.refresh_all_view), name='echo_beatmap_refresh_all'),
            path('refresh-predicted/', self.admin_site.admin_view(self.refresh_predicted_view), name='echo_beatmap_refresh_predicted'),
            path('flush-all-predictions/', self.admin_site.admin_view(self.flush_all_predictions_view), name='echo_flush_all_predictions'),
        ]
        return custom + urls

    def refresh_all_view(self, request: HttpRequest):
        if not request.user.is_staff:
            self.message_user(request, 'Permission denied.', level=messages.ERROR)
            return redirect('..')
        
        def _worker(user_id: int, delay_s: int = 5):
            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return
            rf = RequestFactory()
            for bm_id in Beatmap.objects.values_list('beatmap_id', flat=True).iterator(chunk_size=500):
                # Wait while users are interacting (priority to user actions)
                while True:
                    try:
                        cnt = int(cache.get('user_interaction_counter') or 0)
                    except Exception:
                        cnt = 0
                    wait = cnt > 0
                    if not wait:
                        try:
                            pu = float(cache.get('user_interaction_pause_until') or 0)
                            now_ts = timezone.now().timestamp()
                            wait = pu > now_ts
                        except Exception:
                            wait = False
                    if not wait:
                        break
                    time.sleep(1)
                try:
                    req = rf.post('/update_beatmap_info/', {'beatmap_id': bm_id})
                    req.user = user
                    update_beatmap_info(req)
                except Exception:
                    pass
                time.sleep(delay_s)

        t = threading.Thread(target=_worker, args=(request.user.id, 5), daemon=True)
        t.start()
        self.message_user(request, 'Background refresh started. You may close this tab.')
        return redirect('..')

    def refresh_predicted_view(self, request: HttpRequest):
        if not request.user.is_staff:
            self.message_user(request, 'Permission denied.', level=messages.ERROR)
            return redirect('..')

        def _worker(user_id: int, delay_s: int = 10):
            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return
            rf = RequestFactory()
            # Unique beatmap IDs that have predicted tags
            qs = (
                TagApplication.objects
                .filter(is_prediction=True)
                .values_list('beatmap__beatmap_id', flat=True)
                .distinct()
            )
            for bm_id in qs.iterator(chunk_size=500):
                # Wait while users are interacting (priority to user actions)
                while True:
                    try:
                        cnt = int(cache.get('user_interaction_counter') or 0)
                    except Exception:
                        cnt = 0
                    wait = cnt > 0
                    if not wait:
                        try:
                            pu = float(cache.get('user_interaction_pause_until') or 0)
                            now_ts = timezone.now().timestamp()
                            wait = pu > now_ts
                        except Exception:
                            wait = False
                    if not wait:
                        break
                    time.sleep(1)
                try:
                    req = rf.post('/update_beatmap_info/', {'beatmap_id': bm_id})
                    req.user = user
                    update_beatmap_info(req)
                    # Also update PP fields for this beatmap
                    try:
                        from .helpers.rosu_utils import (
                            get_or_compute_pp,
                            get_or_compute_modded_pps,
                        )
                        bm_obj = Beatmap.objects.filter(beatmap_id=str(bm_id)).first()
                        if bm_obj:
                            get_or_compute_pp(bm_obj)
                            get_or_compute_modded_pps(bm_obj)
                    except Exception:
                        pass
                except Exception:
                    pass
                time.sleep(delay_s)

        t = threading.Thread(target=_worker, args=(request.user.id, 10), daemon=True)
        t.start()
        self.message_user(request, 'Background refresh of predicted-tag beatmaps started (1 every 10s).')
        return redirect('..')

    def flush_all_predictions_view(self, request: HttpRequest):
        if not request.user.is_staff:
            self.message_user(request, 'Permission denied.', level=messages.ERROR)
            return redirect('..')
        # Perform deletion directly to avoid API auth requirements
        try:
            qs = TagApplication.objects.filter(user__isnull=True, is_prediction=True)
            deleted_count, _ = qs.delete()
            self.message_user(request, f'Flushed predictions. Deleted: {deleted_count}.')
        except Exception:
            self.message_user(request, 'Failed to flush predictions.', level=messages.ERROR)
        return redirect('..')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('get_username', 'osu_id', 'banned', 'get_date_joined', 'get_last_login')
    search_fields = ('user__username', 'osu_id')
    list_filter = ('banned',)
    list_select_related = ('user',)

    def get_username(self, obj):
        return obj.user.username
    get_username.admin_order_field = 'user__username'
    get_username.short_description = 'Username'

    def get_date_joined(self, obj):
        return obj.user.date_joined
    get_date_joined.admin_order_field = 'user__date_joined'
    get_date_joined.short_description = 'Date joined'

    def get_last_login(self, obj):
        return obj.user.last_login
    get_last_login.admin_order_field = 'user__last_login'
    get_last_login.short_description = 'Last login'
class TagRelationInline(admin.TabularInline):
    model = TagRelation
    fk_name = 'child'
    extra = 1

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'upvotes', 'downvotes', 'is_locked', 'is_recommended')
    list_filter = ('category', 'is_locked', 'is_recommended')
    search_fields = ('name', 'description')
    inlines = [TagRelationInline]
admin.site.register(TagDescriptionHistory)
admin.site.register(TagApplication)

@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'method', 'path', 'timestamp')
    search_fields = ('user__username', 'path')
    list_filter = ('method', 'timestamp')
    readonly_fields = ('user', 'method', 'path', 'timestamp')


@admin.register(AnalyticsSearchEvent)
class AnalyticsSearchEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'client_id', 'short_query', 'results_count', 'sort', 'predicted_mode')
    search_fields = ('client_id', 'query')
    list_filter = ('sort', 'predicted_mode', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('event_id', 'client_id', 'created_at', 'query', 'tags', 'results_count', 'sort', 'predicted_mode', 'flags')

    def short_query(self, obj):
        try:
            q = obj.query or ''
            return (q[:60] + '…') if len(q) > 60 else q
        except Exception:
            return ''
    short_query.short_description = 'Query'


@admin.register(AnalyticsClickEvent)
class AnalyticsClickEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'client_id', 'action', 'beatmap_id', 'search_event_id')
    search_fields = ('client_id', 'beatmap_id', 'search_event_id', 'action')
    list_filter = ('action', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('client_id', 'created_at', 'action', 'beatmap_id', 'search_event_id', 'meta')
