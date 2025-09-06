from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from rest_framework.routers import DefaultRouter

#  --------  new view imports  --------
from echo.views.home      import about, tag_library
from echo.views.auth      import osu_callback
from echo.views.beatmap   import (
    beatmap_detail, update_beatmap_info, beatmap_timeseries,
    save_tag_timestamps, quick_add_beatmap,
)
from echo.views.search    import search_results, preset_search_farm, preset_search_new_favorites
from echo.views.tags      import (
    modify_tag, get_tags, edit_tags,
    update_tag_description, vote_description, search_tags, edit_ownership, get_tags_bulk,
    configure_tag, tag_tree,
)
from echo.views.userSettings  import (
    settings, confirm_data_deletion, delete_user_data,
)
from echo.views.pages      import error_page_view, custom_404_view
from echo.views.statistics import statistics, statistics_player_data

# DRF viewsets
from echo.views.api import (
    BeatmapViewSet, TagViewSet, TagApplicationViewSet, UserProfileViewSet,
    admin_upload_predictions, admin_upload_tag_applications, admin_refresh_beatmaps, admin_upload_users,
    admin_flush_predictions, admin_flush_all_predictions,
)


router = DefaultRouter()
router.register(r'beatmaps', BeatmapViewSet)
router.register(r'tags', TagViewSet)
router.register(r'tag-applications', TagApplicationViewSet, basename='tagapplication')
router.register(r'user-profiles', UserProfileViewSet, basename='userprofiles')


urlpatterns = [
    path('admin/', admin.site.urls),
    # Make search the default home page while keeping the URL name 'home'
    path('', search_results, name='home'),
    path('about/', about, name='about'),
    path('error/', error_page_view, name='error_page'),
    path('callback', osu_callback, name='osu_callback'),
    path('search_tags/', search_tags, name='search_tags'),
    path('modify_tag/', modify_tag, name='modify_tag'),
    path('get_tags/', get_tags, name='get_tags'),
    path('get_tags_bulk/', get_tags_bulk, name='get_tags_bulk'),
    path('configure_tag/', configure_tag, name='configure_tag'),
    path('tag_tree/', tag_tree, name='tag_tree'),
    path('edit_ownership/', edit_ownership, name='edit_ownership'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('settings/', settings, name='settings'),
    path('search_results/', search_results, name='search_results'),
    path('search/preset/farm/', preset_search_farm, name='search_preset_farm'),
    path('search/preset/new-favorites/', preset_search_new_favorites, name='search_preset_new_favorites'),
    path('statistics/', statistics, name='statistics'),
    path('statistics/player-data/', statistics_player_data, name='statistics_player_data'),
    path('edit_tags/', edit_tags, name='edit_tags'),
    path('update_tag_description/', update_tag_description, name='update_tag_description'),
    path('vote_description/', vote_description, name='vote_description'),
    path('confirm_data_deletion/', confirm_data_deletion, name='confirm_data_deletion'),
    path('delete_user_data/', delete_user_data, name='delete_user_data'),
    path('update_beatmap_info/', update_beatmap_info, name='update_beatmap_info'),
    path('add_beatmap/', quick_add_beatmap, name='quick_add_beatmap'),
    path('tag_library/', tag_library, name='tag_library'),
    


######### API #########
    path('beatmap_detail/<int:beatmap_id>/', beatmap_detail, name='beatmap_detail'),
    path('beatmap_detail/<int:beatmap_id>/timeseries/', beatmap_timeseries, name='beatmap_timeseries'),
    path('beatmap_detail/<int:beatmap_id>/tag_timestamps/save/', save_tag_timestamps, name='beatmap_save_tag_timestamps'),

    # removed redundant tag endpoints now served by tag-applications include

    # REST API endpoints using routers
    path('api/', include(router.urls)),

    # Admin-only upload endpoints
    path('api/admin/upload/predictions/', admin_upload_predictions),
    path('api/admin/upload/tag-applications/', admin_upload_tag_applications),
    path('api/admin/upload/users/', admin_upload_users),
    path('api/admin/refresh/beatmaps/', admin_refresh_beatmaps),
    path('api/admin/flush/predictions/', admin_flush_predictions),
    path('api/admin/flush/predictions/all/', admin_flush_all_predictions),
]

handler404 = 'echo.views.custom_404_view'