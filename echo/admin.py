from django.contrib import admin
from .models import Beatmap, UserProfile, Tag, TagApplication


admin.site.register(Beatmap)
admin.site.register(UserProfile)
admin.site.register(Tag)
admin.site.register(TagApplication)