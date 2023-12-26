from django.urls import path, include
from .views import beatmap_info, search_tags, apply_tag

urlpatterns = [
    path('', beatmap_info, name='beatmap_info'),
]