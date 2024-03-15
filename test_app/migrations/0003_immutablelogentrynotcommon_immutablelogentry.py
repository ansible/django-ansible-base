# Generated by Django 4.2.8 on 2024-03-15 09:11

import ansible_base.lib.abstract_models.immutable
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('test_app', '0002_set_up_resources_test_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='ImmutableLogEntryNotCommon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.CharField(max_length=400)),
            ],
            bases=(ansible_base.lib.abstract_models.immutable.ImmutableModel, models.Model),
        ),
        migrations.CreateModel(
            name='ImmutableLogEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('message', models.CharField(max_length=400)),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
            bases=(ansible_base.lib.abstract_models.immutable.ImmutableModel, models.Model),
        ),
    ]
