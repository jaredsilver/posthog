# Generated by Django 3.0.6 on 2021-03-16 17:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0132_team_test_account_filters"),
    ]

    operations = [
        migrations.AlterField(model_name="featureflag", name="key", field=models.CharField(max_length=64),),
        migrations.AlterField(model_name="featureflag", name="name", field=models.TextField(blank=True),),
    ]
