from django.contrib import admin
from .models import Beatmap, UserProfile, Tag, TagApplication, TagDescriptionHistory
from .models import APIRequestLog

admin.site.register(Beatmap)
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