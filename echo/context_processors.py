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
