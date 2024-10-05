from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from echo.views import home, osu_callback, search_tags, modify_tag, get_tags, profile, search_results, beatmap_info, beatmap_detail, BeatmapViewSet, TagViewSet, TagApplicationViewSet, UserProfileViewSet, tags_for_beatmaps, settings, confirm_data_deletion, delete_user_data

# Commenting out the router for now
router = DefaultRouter()
router.register(r'beatmaps', BeatmapViewSet)
router.register(r'tags', TagViewSet)
router.register(r'tag-applications', TagApplicationViewSet)
router.register(r'user-profiles', UserProfileViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('beatmap_info/', include('echo.urls')),
    path('profile/', profile, name='profile'),
    path('callback', osu_callback, name='osu_callback'),
    path('echo/search_tags/', search_tags, name='search_tags'),
    path('echo/modify_tag/', modify_tag, name='modify_tag'),
    path('echo/get_tags/', get_tags, name='get_tags'),
    path('logout/', LogoutView.as_view(next_page='/beatmap_info/'), name='logout'),
    path('settings/', settings, name='settings'),
    path('search_results/', search_results, name='search_results'),
    path('beatmap/<str:beatmap_id>/', beatmap_info, name='beatmap_info'),
    path('settings/confirm_data_deletion/', confirm_data_deletion, name='confirm_data_deletion'),
    path('settings/delete_user_data/', delete_user_data, name='delete_user_data'),

    # Commenting out API and beatmap-related URLs for now
    path('beatmap_info/<int:beatmap_id>/', beatmap_info, name='beatmap_info'),
    path('beatmap_detail/<int:beatmap_id>/', beatmap_detail, name='beatmap_detail'),

    # Custom endpoint for beatmap tags
    path('api/beatmaps/tags/', tags_for_beatmaps),  # Handles batch requests with pagination
    path('api/beatmaps/<str:beatmap_id>/tags/', tags_for_beatmaps),  # Handles single beatmap requests

    # REST API endpoints using routers
    path('api/', include(router.urls)),
]
