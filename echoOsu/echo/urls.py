from django.urls import path
from django.contrib import admin
from .views import beatmap_info, get_tags

urlpatterns = [
    path('', beatmap_info, name='beatmap_info'),
]