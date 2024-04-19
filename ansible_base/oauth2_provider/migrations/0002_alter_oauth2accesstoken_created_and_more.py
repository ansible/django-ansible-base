# Generated by Django 4.2.11 on 2024-04-19 15:47

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dab_oauth2_provider', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='created',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='created_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='expires',
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='id',
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='modified',
            field=models.DateTimeField(auto_now=True, help_text='The date/time this resource was created'),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='modified_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2accesstoken',
            name='token',
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='created',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='created_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='id',
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='modified',
            field=models.DateTimeField(auto_now=True, help_text='The date/time this resource was created'),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='modified_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='created',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='created_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='expires',
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='id',
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='modified',
            field=models.DateTimeField(auto_now=True, help_text='The date/time this resource was created'),
        ),
        migrations.AlterField(
            model_name='oauth2idtoken',
            name='modified_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='application',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.OAUTH2_PROVIDER_APPLICATION_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='created',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='created_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='id',
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='modified',
            field=models.DateTimeField(auto_now=True, help_text='The date/time this resource was created'),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='modified_by',
            field=models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='token',
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='oauth2refreshtoken',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL),
        ),
    ]
