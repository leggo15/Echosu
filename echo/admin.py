from django.contrib import admin
from .models import Beatmap, UserProfile, Tag, TagApplication


admin.site.register(Beatmap)
admin.site.register(UserProfile)
admin.site.register(Tag)
admin.site.register(TagApplication)

from .models import CustomAPIKey
from rest_framework_api_key.admin import APIKeyModelAdmin

@admin.register(CustomAPIKey)
class CustomAPIKeyModelAdmin(APIKeyModelAdmin):
    pass