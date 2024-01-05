import pytest
from django.test.utils import override_settings

from ansible_base.models.rbac import ObjectRole, RoleDefinition, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.tests.functional.models import Inventory, Organization


@pytest.mark.django_db
def test_org_inv_permissions(rando, inventory, org_inv_rd):
    org_inv_rd.give_permission(rando, inventory.organization)

    assert rando.has_obj_perm(inventory, 'view_inventory')
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert not rando.has_obj_perm(inventory, 'delete_inventory')

    assert rando.has_obj_perm(inventory.organization, 'change_organization')

    assert set(Organization.new_accessible_objects(rando, 'change_organization')) == set([inventory.organization])
    assert set(Inventory.new_accessible_objects(rando, 'view')) == set([inventory])

    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set(['change_inventory', 'view_inventory'])


@pytest.mark.django_db
def test_resource_add_permission(rando, inventory):
    rd, _ = RoleDefinition.objects.get_or_create(permissions=['add_inventory', 'view_organization'], name='can-add-inventory')
    rd.give_permission(rando, inventory.organization)

    assert set(RoleEvaluation.get_permissions(rando, inventory.organization)) == set(['add_inventory', 'view_organization'])
    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set()

    assert rando.has_obj_perm(inventory.organization, 'add_inventory')


@pytest.mark.django_db
def test_visible_roles():
    org1 = Organization.objects.create(name='org1')
    org2 = Organization.objects.create(name='org2')

    u1 = permission_registry.user_model.objects.create(username='u1')
    u2 = permission_registry.user_model.objects.create(username='u2')

    rd, _ = RoleDefinition.objects.get_or_create(permissions=['change_organization', 'view_organization'], name='change-org')

    change_1 = rd.give_permission(u1, org1)
    change_2 = rd.give_permission(u2, org2)

    view_rd, _ = RoleDefinition.objects.get_or_create(permissions=['change_organization', 'view_organization'], name='view-org')

    view_1 = view_rd.give_permission(u2, org1)

    # The organization change role grants view permission, so the view role should be visible to the org admin
    assert set(ObjectRole.visible_roles(u1)) == set([change_1, view_1])

    # Likewise is not true in reverse, just having view permision to org does not mean you can see all the roles
    assert set(ObjectRole.visible_roles(u2)) == set([change_2, view_1])


@pytest.mark.django_db
@override_settings(ROLE_BYPASS_SUPERUSER_FLAGS=['is_superuser'])
def test_superuser_can_do_anything(inventory):
    user = permission_registry.user_model.objects.create(username='superuser', is_superuser=True)
    assert user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
@override_settings(ROLE_BYPASS_SUPERUSER_FLAGS=[])
def test_superuser_flag_not_considered(inventory):
    user = permission_registry.user_model.objects.create(username='superuser', is_superuser=True)
    assert not user.has_obj_perm(inventory, 'change')
