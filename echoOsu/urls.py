from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from echo.views import api_token, home, osu_callback, search_tags, modify_tag, get_tags, profile, search_results, beatmap_detail, BeatmapViewSet, TagViewSet, TagApplicationViewSet, UserProfileViewSet, tags_for_beatmaps, settings, confirm_data_deletion, delete_user_data


router = DefaultRouter()
router.register(r'beatmaps', BeatmapViewSet)
router.register(r'tags', TagViewSet)
router.register(r'tag-applications', TagApplicationViewSet, basename='tagapplication')
router.register(r'user-profiles', UserProfileViewSet, basename='userprofiles')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('profile/', profile, name='profile'),
    path('callback', osu_callback, name='osu_callback'),
    path('echo/search_tags/', search_tags, name='search_tags'),
    path('echo/modify_tag/', modify_tag, name='modify_tag'),
    path('echo/get_tags/', get_tags, name='get_tags'),
    path('logout/', LogoutView.as_view(next_page='/beatmap_info/'), name='logout'),
    path('settings/', settings, name='settings'),
    path('search_results/', search_results, name='search_results'),
    path('settings/confirm_data_deletion/', confirm_data_deletion, name='confirm_data_deletion'),
    path('settings/delete_user_data/', delete_user_data, name='delete_user_data'),

    # Commenting out API and beatmap-related URLs for now
    path('api-token/', api_token, name='api_token'),
    path('beatmap_detail/<int:beatmap_id>/', beatmap_detail, name='beatmap_detail'),

    # Custom endpoint for beatmap tags
    path('api/beatmaps/tags/', tags_for_beatmaps),  # Handles batch requests with pagination
    path('api/beatmaps/<str:beatmap_id>/tags/', tags_for_beatmaps),  # Handles single beatmap requests

    # REST API endpoints using routers
    path('api/', include(router.urls)),
]
