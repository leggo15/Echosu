from .models import UserProfile, UserSettings

def add_user_profile_to_context(request):
    # Defaults
    prefs = {
        'tag_category_display': 'none',
        'group_related_tags': False,
        # Visibility defaults: all shown by default
        'show_star_rating': True,
        'show_status': True,
        'show_cs': True,
        'show_hp': True,
        'show_od': True,
        'show_ar': True,
        'show_bpm': True,
        'show_length': True,
        'show_year': True,
        'show_playcount': True,
        'show_favourites': True,
        'show_genres': True,
        'show_pp_nm': True,
        'show_pp_hd': True,
        'show_pp_hr': True,
        'show_pp_dt': True,
        'show_pp_ht': True,
        'show_pp_ez': True,
        'show_pp_fl': True,
        'show_pp_calculator': True,
    }

    # Load from authenticated user's settings if available
    try:
        if getattr(request, 'user', None) and request.user.is_authenticated:
            s = getattr(request.user, 'settings', None)
            if s:
                for key in list(prefs.keys()):
                    if hasattr(s, key):
                        prefs[key] = getattr(s, key)
    except Exception:
        pass

    osu_id = request.session.get('osu_id')
    if osu_id:
        try:
            profile = UserProfile.objects.get(osu_id=osu_id)
            prefs['user_profile'] = profile
        except UserProfile.DoesNotExist:
            pass
    return prefs


from django.conf import settings

def osu_oauth_url(request):
    """Constructs the osu OAuth login URL."""
    client_id = settings.SOCIAL_AUTH_OSU_KEY
    redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI
    oauth_url = f"https://osu.ppy.sh/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=identify"
    
    return {
        'osu_oauth_url': oauth_url
    }
