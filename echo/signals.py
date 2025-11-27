from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Beatmap, ManiaKeyOption


@receiver(post_save, sender=Beatmap)
def ensure_mania_key_option(sender, instance, **kwargs):
    mode = (instance.mode or '').lower()
    if mode != 'mania':
        return
    ManiaKeyOption.ensure_for_value(instance.cs)

