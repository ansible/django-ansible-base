# Generated by Django 4.2.8 on 2024-02-01 17:28

from django.conf import settings
import django.contrib.auth.models
import django.contrib.auth.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_system_user(apps, schema_editor):
    """
    Create the system user using the username in settings.

    The user is self-referential in its created_by and modified_by fields.
    It is inactive, only used for attributing internal changes to the system.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)

    system_username = settings.SYSTEM_USERNAME
    if not User.objects.filter(username=system_username).exists():
        system_user = User.objects.create(username=system_username, is_active=False)
        system_user.created_by = system_user
        system_user.modified_by = system_user
        system_user.save()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512, unique=True)),
                ('description', models.TextField(blank=True, default='', help_text='The organization description.')),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('description', models.TextField(blank=True, default='', help_text='The team description.')),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(help_text='The organization of this team.', on_delete=django.db.models.deletion.CASCADE, related_name='teams', to='test_app.organization')),
            ],
            options={
                'ordering': ('organization__name', 'name'),
                'abstract': False,
                'unique_together': {('organization', 'name')},
            },
        ),
        migrations.CreateModel(
            name='RelatedFieldsTestModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
                ('more_teams', models.ManyToManyField(related_name='related_fields_test_model_more_teams', to='test_app.team')),
                ('teams_with_no_view', models.ManyToManyField(related_name='related_fields_test_model_teams_with_no_view', to='test_app.team')),
                ('users', models.ManyToManyField(related_name='related_fields_test_model_users', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='EncryptionModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('testing1', models.CharField(default='a', max_length=400, null=True)),
                ('testing2', models.CharField(default='b', max_length=400, null=True)),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='team',
            name='encryptioner',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='test_app.encryptionmodel'),
        ),
        migrations.RunPython(create_system_user),
    ]
