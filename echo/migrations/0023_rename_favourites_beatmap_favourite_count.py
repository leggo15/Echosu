# Generated by Django 5.0.2 on 2024-10-28 17:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('echo', '0022_beatmap_favourites_beatmap_playcount'),
    ]

    operations = [
        migrations.RenameField(
            model_name='beatmap',
            old_name='favourites',
            new_name='favourite_count',
        ),
    ]
