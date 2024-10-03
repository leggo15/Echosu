from .models import UserProfile

def add_user_profile_to_context(request):
    osu_id = request.session.get('osu_id')
    if osu_id:
        try:
            profile = UserProfile.objects.get(osu_id=osu_id)
            return {'user_profile': profile}
        except UserProfile.DoesNotExist:
            # If the profile doesn't exist, return an empty context
            return {}
    return {}


from django.conf import settings

def osu_oauth_url(request):
    """Constructs the osu OAuth login URL."""
    client_id = settings.SOCIAL_AUTH_OSU_KEY
    redirect_uri = settings.SOCIAL_AUTH_OSU_REDIRECT_URI
    oauth_url = f"https://osu.ppy.sh/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=identify"
    
    return {
        'osu_oauth_url': oauth_url
    }
