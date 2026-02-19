from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('microsub_client', '0004_usersettings_dismissedbroadcast'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersettings',
            name='infinite_scroll',
            field=models.BooleanField(default=False),
        ),
    ]
