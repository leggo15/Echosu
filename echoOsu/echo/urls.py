from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.home, name='echo.home'),
    path('add_tag/<int:beatmap_id>/', views.add_tag, name='add_tag'),
    path('beatmap_info/', views.beatmap_info, name='beatmap_info'),
    path('add_tag_to_beatmap/', views.add_tag_to_beatmap, name='add_tag_to_beatmap'),
    path('callback', views.osu_callback, name='osu_callback'),
]