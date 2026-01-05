from django.db import migrations, models


def backfill_breakdown(apps, schema_editor):
    HourlyActiveUserCount = apps.get_model('echo', 'HourlyActiveUserCount')
    # Existing rows only had `count`. Assume all are nonstaff by default.
    for row in HourlyActiveUserCount.objects.all().iterator():
        try:
            c = int(getattr(row, 'count', 0) or 0)
        except Exception:
            c = 0
        row.staff_count = 0
        row.nonstaff_count = max(0, c)
        row.save(update_fields=['staff_count', 'nonstaff_count'])


class Migration(migrations.Migration):

    dependencies = [
        ('echo', '0018_hourlyactiveusercount'),
    ]

    operations = [
        migrations.AddField(
            model_name='hourlyactiveusercount',
            name='staff_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='hourlyactiveusercount',
            name='nonstaff_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_breakdown, migrations.RunPython.noop),
    ]


