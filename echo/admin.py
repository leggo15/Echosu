from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.test.client import RequestFactory
import time

from .models import Beatmap, UserProfile, Tag, TagApplication, TagDescriptionHistory
from .models import APIRequestLog
from .views.beatmap import update_beatmap_info

@admin.register(Beatmap)
class BeatmapAdmin(admin.ModelAdmin):
    list_display = ('beatmap_id', 'title', 'artist', 'creator', 'status')
    search_fields = ('beatmap_id', 'title', 'artist', 'creator')

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
        success = 0
        failed = 0
        for bm_id in Beatmap.objects.values_list('beatmap_id', flat=True).iterator(chunk_size=500):
            rf = RequestFactory()
            req = rf.post('/update_beatmap_info/', {'beatmap_id': bm_id})
            req.user = request.user
            resp = update_beatmap_info(req)
            if getattr(resp, 'status_code', 500) == 200:
                success += 1
            else:
                failed += 1
            time.sleep(5)
        self.message_user(request, f"Refresh complete. Success: {success}, Failed: {failed}.")
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
