from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from echo.views import (
    vote_description,
    confirm_data_deletion,
    delete_user_data,
    update_tag_description,
    edit_tags,
    api_token,
    home,
    about,
    osu_callback,
    search_tags,
    modify_tag,
    get_tags,
    profile,
    search_results,
    beatmap_detail,
    BeatmapViewSet,
    TagViewSet,
    TagApplicationViewSet,
    UserProfileViewSet,
    tags_for_beatmaps,
    settings,
    error_page_view,
    load_more_recommendations,
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


######### API #########
    path('api-token/', api_token, name='api_token'),
    path('beatmap_detail/<int:beatmap_id>/', beatmap_detail, name='beatmap_detail'),

    # endpoint for beatmap tags
    path('api/beatmaps/tags/', tags_for_beatmaps),
    path('api/beatmaps/<str:beatmap_id>/tags/', tags_for_beatmaps),  # Handles single beatmap requests

    # REST API endpoints using routers
    path('api/', include(router.urls)),
]
