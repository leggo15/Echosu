from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import Tag, TagApplication


class Command(BaseCommand):
    help = 'Ensure tag applications use mode-specific tags.'

    def handle(self, *args, **options):
        mismatches = 0
        reassigned = 0
        created_tags = 0
        deleted_apps = 0

        qs = (
            TagApplication.objects
            .select_related('tag', 'beatmap')
            .order_by('id')
        )

        for app in qs:
            beatmap = app.beatmap
            tag = app.tag
            if not beatmap or not tag:
                continue
            desired_mode = Tag.normalize_mode(getattr(beatmap, 'mode', None))
            current_mode = Tag.normalize_mode(getattr(tag, 'mode', None))
            if desired_mode == current_mode:
                continue

            mismatches += 1

            with transaction.atomic():
                try:
                    new_tag, created = Tag.get_or_create_for_mode(tag.name, beatmap.mode)
                except ValueError:
                    continue

                if created:
                    created_tags += 1

                # If an identical tag application already exists with the correct tag, drop this one
                conflict = TagApplication.objects.filter(
                    tag=new_tag,
                    beatmap=beatmap,
                    user=app.user,
                    true_negative=app.true_negative,
                    is_prediction=app.is_prediction,
                ).exclude(id=app.id).first()

                if conflict:
                    app.delete()
                    deleted_apps += 1
                    continue

                app.tag = new_tag
                app.save(update_fields=['tag'])
                reassigned += 1

        self.stdout.write(self.style.SUCCESS(
            f'Processed tag mode mismatches: found={mismatches}, '
            f'reassigned={reassigned}, deleted={deleted_apps}, created_tags={created_tags}'
        ))

