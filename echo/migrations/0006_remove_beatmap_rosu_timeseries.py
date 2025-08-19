from django.db import migrations


class Migration(migrations.Migration):

	dependencies = [
		('echo', '0005_apirequestlog_status_code'),
	]

	operations = [
		migrations.RemoveField(
			model_name='beatmap',
			name='rosu_timeseries',
		),
	]


