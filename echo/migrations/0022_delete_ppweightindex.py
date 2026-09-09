from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('echo', '0021_ppweightindex'),
    ]

    operations = [
        migrations.DeleteModel(name='PpWeightIndex'),
    ]
