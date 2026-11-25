"""POC: add automation dashboard permissions under organizations.

This migration demonstrates the complete consumer-side recipe:

1. ``AlterModelOptions`` adds the new codenames to ``Organization.Meta.permissions``.
2. The data migration materializes the DAB permissions *before* using them.
   DAB normally syncs ``DABPermission`` from model ``Meta`` in a ``post_migrate``
   signal, which has not run yet while this migration is executing. Consumers
   that create role definitions in the same migration must call
   ``create_dab_permissions`` themselves (this mirrors what AWX does in
   ``awx/main/migrations/_dab_rbac.py``).
3. The two organization-scoped role definitions are created with an explicit
   ``content_type`` for the organization model. Omitting the content type would
   create system-wide roles instead.
"""

from django.apps import apps as global_apps
from django.db import migrations, models

from ansible_base.rbac.management import create_dab_permissions

VIEWER_ROLE = 'Automation Dashboard Viewer'
EDITOR_ROLE = 'Automation Dashboard Editor'


def create_automation_dashboard_roles(apps, schema_editor):
    # Ensure DABPermission rows exist before we reference them by codename.
    create_dab_permissions(global_apps.get_app_config('dab_rbac'), apps=apps)

    DABContentType = apps.get_model('dab_rbac', 'DABContentType')
    DABPermission = apps.get_model('dab_rbac', 'DABPermission')
    RoleDefinition = apps.get_model('dab_rbac', 'RoleDefinition')
    Organization = apps.get_model('test_app', 'Organization')

    org_ct = DABContentType.objects.get_for_model(Organization)

    def perm(codename):
        return DABPermission.objects.get(content_type=org_ct, codename=codename)

    viewer_permissions = [
        perm('view_organization'),
        perm('view_automation_dashboard_organization'),
    ]
    editor_permissions = viewer_permissions + [
        perm('change_automation_dashboard_organization'),
    ]

    for name, description, permissions in (
        (VIEWER_ROLE, 'Can view the automation dashboard for a single organization', viewer_permissions),
        (EDITOR_ROLE, 'Can view and edit the automation dashboard for a single organization', editor_permissions),
    ):
        role_definition, _ = RoleDefinition.objects.get_or_create(
            name=name,
            defaults={
                'description': description,
                'content_type': org_ct,
                'managed': True,
            },
        )
        role_definition.permissions.set(permissions)


def remove_automation_dashboard_roles(apps, schema_editor):
    RoleDefinition = apps.get_model('dab_rbac', 'RoleDefinition')
    RoleDefinition.objects.filter(name__in=[VIEWER_ROLE, EDITOR_ROLE]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('test_app', '0019_metadata_test_model'),
        ('dab_rbac', '__first__'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='organization',
            options={
                'ordering': ['id'],
                'permissions': [
                    ('member_organization', 'User is member of this organization'),
                    ('view_automation_dashboard_organization', 'Can view the automation dashboard for this organization'),
                    ('change_automation_dashboard_organization', 'Can edit the automation dashboard for this organization'),
                ],
            },
        ),
        migrations.RunPython(create_automation_dashboard_roles, remove_automation_dashboard_roles),
    ]
