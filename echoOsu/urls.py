from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from rest_framework.routers import DefaultRouter

#  --------  new view imports  --------
from echo.views.home      import home, about, load_more_recommendations, tag_library
from echo.views.auth      import osu_callback, api_token
from echo.views.profile   import profile, user_stats
from echo.views.beatmap   import (
    beatmap_detail, update_beatmap_info,
)
from echo.views.search    import search_results
from echo.views.tags      import (
    modify_tag, get_tags, edit_tags,
    update_tag_description, vote_description, search_tags
)
from echo.views.userSettings  import (
    settings, confirm_data_deletion, delete_user_data,
)
from echo.views.pages      import error_page_view, custom_404_view

# DRF viewsets
from echo.views.api import (
    BeatmapViewSet, TagViewSet, TagApplicationViewSet, UserProfileViewSet, tags_for_beatmaps
)


router = DefaultRouter()
router.register(r'beatmaps', BeatmapViewSet)
router.register(r'tags', TagViewSet)
router.register(r'tag-applications', TagApplicationViewSet, basename='tagapplication')
router.register(r'user-profiles', UserProfileViewSet, basename='userprofiles')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('profile/', profile, name='profile'),
    path('about/', about, name='about'),
    path('error/', error_page_view, name='error_page'),
    path('callback', osu_callback, name='osu_callback'),
    path('search_tags/', search_tags, name='search_tags'),
    path('modify_tag/', modify_tag, name='modify_tag'),
    path('get_tags/', get_tags, name='get_tags'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('settings/', settings, name='settings'),
    path('search_results/', search_results, name='search_results'),
    path('edit_tags/', edit_tags, name='edit_tags'),
    path('update_tag_description/', update_tag_description, name='update_tag_description'),
    path('vote_description/', vote_description, name='vote_description'),
    path('confirm_data_deletion/', confirm_data_deletion, name='confirm_data_deletion'),
    path('delete_user_data/', delete_user_data, name='delete_user_data'),
    path('load_more_recommendations/', load_more_recommendations, name='load_more_recommendations'),
    path('update_beatmap_info/', update_beatmap_info, name='update_beatmap_info'),
    path('tag_library/', tag_library, name='tag_library'),
    path('statistics/', user_stats, name='user_stats'),
    


######### API #########
    path('api-token/', api_token, name='api_token'),
    path('beatmap_detail/<int:beatmap_id>/', beatmap_detail, name='beatmap_detail'),

    # endpoint for beatmap tags
    path('api/beatmaps/tags/', tags_for_beatmaps),
    path('api/beatmaps/<str:beatmap_id>/tags/', tags_for_beatmaps),  # Handles single beatmap requests

    # REST API endpoints using routers
    path('api/', include(router.urls)),
]

handler404 = 'echo.views.custom_404_view'