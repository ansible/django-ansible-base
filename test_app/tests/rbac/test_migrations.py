import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.test.utils import override_settings

from ansible_base.rbac.migrations._managed_definitions import setup_managed_role_definitions
from ansible_base.rbac.migrations._utils import give_permissions
from ansible_base.rbac.models import DABPermission, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Team, User

INVENTORY_OBJ_PERMISSIONS = ['view_inventory', 'change_inventory', 'delete_inventory', 'update_inventory']


@pytest.mark.django_db
def test_managed_definitions_precreate():
    with override_settings(
        ANSIBLE_BASE_ROLE_PRECREATE={
            'object_admin': '{cls._meta.model_name}-admin',
            'org_admin': 'organization-admin',
            'org_children': 'organization-{cls._meta.model_name}-admin',
            'special': '{cls._meta.model_name}-{action}',
        }
    ):
        setup_managed_role_definitions(apps, None)
    rd = RoleDefinition.objects.get(name='inventory-admin')
    assert rd.managed is True
    # add permissions do not go in the object-level admin
    assert set(rd.permissions.values_list('codename', flat=True)) == set(INVENTORY_OBJ_PERMISSIONS)

    # test org-level object admin permissions
    rd = RoleDefinition.objects.get(name='organization-inventory-admin')
    assert rd.managed is True
    assert set(rd.permissions.values_list('codename', flat=True)) == set(['add_inventory', 'view_organization'] + INVENTORY_OBJ_PERMISSIONS)


@pytest.mark.django_db
def test_managed_definitions_custom_obj_admin_name():
    with override_settings(
        ANSIBLE_BASE_ROLE_PRECREATE={
            'object_admin': 'foo-{cls._meta.model_name}-foo',
        }
    ):
        setup_managed_role_definitions(apps, None)
    rd = RoleDefinition.objects.get(name='foo-inventory-foo')
    assert rd.managed is True
    # add permissions do not go in the object-level admin
    assert set(rd.permissions.values_list('codename', flat=True)) == set(INVENTORY_OBJ_PERMISSIONS)


@pytest.mark.django_db
def test_give_permissions(organization, inventory, inv_rd):
    user = User.objects.create(username='user')
    team = Team.objects.create(name='ateam', organization=organization)
    give_permissions(apps, inv_rd, users=[user], teams=[team], object_id=inventory.id, content_type_id=ContentType.objects.get_for_model(inventory).id)
    assert RoleUserAssignment.objects.filter(user=user).exists()
    assert RoleTeamAssignment.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_give_permissions_by_id(organization, inventory, inv_rd):
    team = Team.objects.create(name='ateam', organization=organization)
    give_permissions(apps, inv_rd, teams=[team.id], object_id=inventory.id, content_type_id=ContentType.objects.get_for_model(inventory).id)
    assert RoleTeamAssignment.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_permission_migration():
    "These are expected to be created via a post_migrate signal just like auth.Permission"
    assert len(DABPermission.objects.order_by('content_type').values_list('content_type').distinct()) == len(permission_registry.all_registered_models)
