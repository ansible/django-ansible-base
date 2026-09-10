from io import StringIO

import pytest
from django.apps import apps

from ansible_base.rbac.management import create_dab_permissions
from ansible_base.rbac.management.commands.RBAC_checks import Command
from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition
from test_app.models import Inventory, PublicData


def run_and_get_output():
    from django.core.management.base import CommandError

    cmd = Command()
    cmd.stdout = StringIO()
    try:
        cmd.handle()
    except CommandError:
        pass
    return cmd.stdout.getvalue()


@pytest.mark.django_db
def test_successful_no_data():
    assert "checking for up-to-date role evaluations" in run_and_get_output()


@pytest.mark.django_db
def test_role_definition_wrong_model(organization):
    inventory = Inventory.objects.create(name='foo-inv', organization=organization)
    rd, _ = RoleDefinition.objects.get_or_create(name='foo-def', permissions=['view_organization'])
    orole = ObjectRole.objects.create(object_id=inventory.id, content_type=DABContentType.objects.get_for_model(inventory), role_definition=rd)
    assert f"Object role {orole} has permission view_organization for an unlike content type" in run_and_get_output()


@pytest.mark.django_db
def test_role_definition_no_view_perm_not_flagged(organization):
    """Roles for models that have no view_ permission registered should not be flagged.

    Regression test for https://github.com/ansible/django-ansible-base/issues/507.
    PublicData has default_permissions = ('add', 'change', 'delete') — no view.
    A role that only grants change_publicdata should not produce a warning.
    """
    ct = DABContentType.objects.get_for_model(PublicData)
    assert not ct.dab_permissions.filter(codename__startswith='view_').exists(), "PublicData should have no view_ permission"
    RoleDefinition.objects.get_or_create(
        name='public-data-admin',
        defaults={
            'content_type': ct,
        },
    )
    output = run_and_get_output()
    assert 'public-data-admin does not list any view permissions' not in output


@pytest.mark.django_db
def test_recreate_model_permissions():
    del_ct = 0
    for permission in DABPermission.objects.filter(content_type__model='inventory'):
        permission.delete()
        del_ct += 1
    assert del_ct == 5
    create_dab_permissions(app_config=apps.get_app_config('dab_rbac'))
    assert DABPermission.objects.filter(content_type__model='inventory').count() == 5
