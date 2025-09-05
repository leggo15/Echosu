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

from .models import Beatmap, UserProfile, Tag, TagApplication, TagDescriptionHistory
from .models import APIRequestLog
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
                try:
                    req = rf.post('/update_beatmap_info/', {'beatmap_id': bm_id})
                    req.user = user
                    update_beatmap_info(req)
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
        # Call the API view directly with a forged request for consistency
        rf = RequestFactory()
        req = rf.post('/api/admin/flush/predictions/all/', data={})
        req.user = request.user
        try:
            resp = admin_flush_all_predictions(req)
            try:
                deleted = getattr(resp, 'data', {}).get('deleted')
            except Exception:
                deleted = None
            self.message_user(request, f'Flushed predictions. Deleted: {deleted if deleted is not None else "unknown"}.')
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
admin.site.register(Tag)
admin.site.register(TagDescriptionHistory)
admin.site.register(TagApplication)

@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'method', 'path', 'timestamp')
    search_fields = ('user__username', 'path')
    list_filter = ('method', 'timestamp')
    readonly_fields = ('user', 'method', 'path', 'timestamp')
