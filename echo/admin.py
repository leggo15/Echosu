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

@admin.register(Beatmap)
class BeatmapAdmin(admin.ModelAdmin):
    list_display = ('beatmap_id', 'title', 'artist', 'creator', 'status')
    search_fields = ('beatmap_id', 'title', 'artist', 'creator')
    change_list_template = 'admin/echo/beatmap/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('refresh-all/', self.admin_site.admin_view(self.refresh_all_view), name='echo_beatmap_refresh_all'),
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
admin.site.register(UserProfile)
admin.site.register(Tag)
admin.site.register(TagDescriptionHistory)
admin.site.register(TagApplication)

@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'method', 'path', 'timestamp')
    search_fields = ('user__username', 'path')
    list_filter = ('method', 'timestamp')
    readonly_fields = ('user', 'method', 'path', 'timestamp')
