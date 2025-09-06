from .models import UserProfile, UserSettings

def add_user_profile_to_context(request):
    # Default preference
    tag_display = 'color'
    # Prefer from authenticated user's settings if present
    try:
        if getattr(request, 'user', None) and request.user.is_authenticated:
            s = getattr(request.user, 'settings', None)
            if s and getattr(s, 'tag_category_display', None):
                tag_display = s.tag_category_display
    except Exception:
        pass

    osu_id = request.session.get('osu_id')
    if osu_id:
        try:
            profile = UserProfile.objects.get(osu_id=osu_id)
            return {'user_profile': profile, 'tag_category_display': tag_display}
        except UserProfile.DoesNotExist:
            return {'tag_category_display': tag_display}
    return {'tag_category_display': tag_display}


from django.conf import settings

def osu_oauth_url(request):
    """Constructs the osu OAuth login URL."""
    client_id = settings.SOCIAL_AUTH_OSU_KEY
    redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI
    oauth_url = f"https://osu.ppy.sh/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=identify"
    
    return {
        'osu_oauth_url': oauth_url
    }
