from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('echo', '0020_delete_hourlyactiveusercount_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PpWeightIndex',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(choices=[('osu', 'osu!'), ('taiko', 'Taiko'), ('fruits', 'Catch'), ('mania', 'Mania')], db_index=True, max_length=16, unique=True)),
                ('degree', models.PositiveSmallIntegerField(default=4)),
                ('coefficients', models.JSONField(blank=True, default=list)),
                ('source_count', models.PositiveIntegerField(default=0)),
                ('star_min', models.FloatField(blank=True, null=True)),
                ('star_max', models.FloatField(blank=True, null=True)),
                ('rmse_pp', models.FloatField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
            ],
            options={
                'indexes': [models.Index(fields=['mode', 'updated_at'], name='echo_ppweig_mode_4a1fda_idx')],
            },
        ),
    ]


