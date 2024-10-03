from django.urls import path
from django.contrib import admin
from .views import beatmap_info

urlpatterns = [
    path('', beatmap_info, name='beatmap_info'),
]
