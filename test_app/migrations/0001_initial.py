# Generated by Django 4.2.8 on 2024-02-01 17:28

import uuid

from django.conf import settings
import django.contrib.auth.models
import django.contrib.auth.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


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
            options={'ordering': ['id'], 'verbose_name': 'user', 'verbose_name_plural': 'users'},
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
                ('admins', models.ManyToManyField(blank=True, help_text='The list of admins for this organization', related_name='admin_of_organizations', to=settings.AUTH_USER_MODEL)),
                ('users', models.ManyToManyField(blank=True, help_text='The list of users on this organization', related_name='member_of_organizations', to=settings.AUTH_USER_MODEL))
            ],
            options={'ordering': ['id'], 'permissions': [('member_organization', 'User is member of this organization')]},
        ),
        migrations.CreateModel(
            name='EncryptionModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
                ('testing1', models.CharField(default='a', max_length=400, null=True)),
                ('testing2', models.CharField(default='b', max_length=400, null=True)),
            ],
            options={'ordering': ['id']},
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
                ('organization', models.ForeignKey(help_text='The organization of this team.', on_delete=django.db.models.deletion.CASCADE, related_name='teams', to=settings.ANSIBLE_BASE_ORGANIZATION_MODEL)),
                ('team_parents', models.ManyToManyField(blank=True, related_name='team_children', to=settings.ANSIBLE_BASE_TEAM_MODEL)),
            ],
            options={
                'ordering': ('organization__name', 'name'),
                'abstract': False,
                'unique_together': {('organization', 'name')},
                'permissions': [('member_team', 'Has all roles assigned to this team')],
            },
        ),
        migrations.CreateModel(
            name='ExampleEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='InstanceGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=512)),
            ],
        ),
        migrations.CreateModel(
            name='Namespace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.ANSIBLE_BASE_ORGANIZATION_MODEL, related_name='namespaces')),
            ],
        ),
        migrations.CreateModel(
            name='Credential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=512)),
                ('organization', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='credentials', to='test_app.organization')),
            ],
            options={
                'ordering': ['id'],
                'permissions': [('use_credential', 'Apply credential to other models')],
            },
        ),
        migrations.CreateModel(
            name='Inventory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=512)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.ANSIBLE_BASE_ORGANIZATION_MODEL, null=True, related_name='inventories')),
                ('credential', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventories', to='test_app.credential'),)
            ],
            options={
                'permissions': [('update_inventory', 'Do inventory updates')],
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='CollectionImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
                ('namespace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.namespace', related_name='collections')),
            ],
        ),
        migrations.CreateModel(
            name='UUIDModel',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.organization', related_name='uuidmodels')),
            ],
        ),
        migrations.CreateModel(
            name='Cow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.organization', related_name='cows')),
            ],
            options={'ordering': ['id'], 'permissions': [('say_cow', 'Make cow say some advice')]},
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
        migrations.AddField(
            model_name='team',
            name='encryptioner',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='test_app.encryptionmodel'),
        ),
        migrations.CreateModel(
            name='ImmutableTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'permissions': [('cancel_immutabletask', 'Stop this task from running')],
                'default_permissions': ('add', 'view', 'delete'),
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='ProxyInventory',
            fields=[
            ],
            options={
                'permissions': [('view_inventory', 'Can view inventory'), ('change_inventory', 'Can change inventory'), ('add_inventory', 'Can add inventory'), ('delete_inventory', 'Can delete inventory')],
                'proxy': True,
                'indexes': [],
                'constraints': [],
                'ordering': ['id'],
            },
            bases=('test_app.inventory',),
        ),
        migrations.CreateModel(
            name='WeirdPerm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.organization', related_name='weirdperms')),
            ],
            options={
                'permissions': [("I'm a lovely coconut", 'You can be a lovely coconut with this object'), ('crack', 'Can crack open this coconut')],
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='PositionModel',
            fields=[
                ('position', models.BigIntegerField(primary_key=True, serialize=False)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.organization', related_name='positionmodels')),
            ],
        ),
        migrations.CreateModel(
            name='ParentName',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('my_organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='test_app.organization', related_name='parentnames')),
            ],
        ),
        migrations.CreateModel(
            name='Original2',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Original1',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Proxy1',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('test_app.original1',),
        ),
        migrations.CreateModel(
            name='Proxy2',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('test_app.original2',),
        ),
        migrations.CreateModel(
            name='MemberGuide',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('modified', models.DateTimeField(auto_now=True, help_text='The date/time this resource was created')),
                ('created', models.DateTimeField(auto_now_add=True, help_text='The date/time this resource was created')),
                ('name', models.CharField(help_text='The name of this resource', max_length=512)),
                ('article', models.TextField(default='-- Help article stub --')),
                ('created_by', models.ForeignKey(default=None, editable=False, help_text='The user who created this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created+', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, help_text='The user who last modified this resource', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(help_text='Docs for all org members', on_delete=django.db.models.deletion.CASCADE, related_name='member_guides', to='test_app.organization')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
