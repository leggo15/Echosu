from django import template
from django.db.models import Count
from echo.models import TagApplication

register = template.Library()

@register.filter
def has_tag_edit_permission(user):
    if not user.is_authenticated:
        return False
    tagged_maps_count = TagApplication.objects.filter(user=user).values('beatmap').distinct().count()
    return tagged_maps_count >= 5
