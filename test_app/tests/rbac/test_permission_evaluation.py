import pytest
from django.test.utils import override_settings

from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization


@pytest.mark.django_db
def test_org_inv_permissions_user(rando, inventory, org_inv_change_rd):
    assert not rando.has_obj_perm(inventory, 'view_inventory')
    assert not rando.has_obj_perm(inventory, 'change_inventory')
    assert list(Inventory.access_qs(rando)) == []

    org_inv_change_rd.give_permission(rando, inventory.organization)

    assert rando.has_obj_perm(inventory, 'view_inventory')
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert not rando.has_obj_perm(inventory, 'delete_inventory')

    assert rando.has_obj_perm(inventory.organization, 'change_organization')

    assert set(Organization.access_qs(rando, 'change_organization')) == set([inventory.organization])
    assert set(Inventory.access_qs(rando, 'view')) == set([inventory])

    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set(['change_inventory', 'view_inventory'])
    assert list(Inventory.access_qs(rando)) == [inventory]


@pytest.mark.django_db
def test_org_inv_permissions_team(team, inventory, org_inv_change_rd):
    "We support using team as actor in model methods like MyModel.access_qs(team) but do not attach has_obj_perm"
    assert list(Inventory.access_qs(team)) == []
    assert list(Inventory.access_ids_qs(team)) == []

    org_inv_change_rd.give_permission(team, inventory.organization)

    assert set(Organization.access_qs(team, 'change_organization')) == set([inventory.organization])
    assert set(Inventory.access_qs(team, 'view')) == set([inventory])

    assert set(RoleEvaluation.get_permissions(team, inventory)) == set(['change_inventory', 'view_inventory'])
    assert list(Inventory.access_qs(team)) == [inventory]
    assert list(Inventory.access_ids_qs(team)) == [(inventory.id,)]


@pytest.mark.django_db
def test_access_qs_with_parent_qs(inventory, rando, inv_rd):
    assert list(Inventory.access_qs(rando)) == []
    inv_rd.give_permission(rando, inventory)
    assert list(Inventory.access_qs(rando)) == [inventory]
    assert list(Inventory.access_qs(rando, queryset=Inventory.objects.all())) == [inventory]
    assert list(Inventory.access_qs(rando, queryset=Inventory.objects.none())) == []


@pytest.mark.django_db
def test_resource_add_permission(rando, inventory):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['add_inventory', 'view_organization'],
        name='can-add-inventory',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    rd.give_permission(rando, inventory.organization)

    assert set(RoleEvaluation.get_permissions(rando, inventory.organization)) == set(['add_inventory', 'view_organization'])
    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set()

    assert rando.has_obj_perm(inventory.organization, 'add_inventory')


@pytest.mark.django_db
def test_visible_items():
    org1 = Organization.objects.create(name='org1')
    org2 = Organization.objects.create(name='org2')
    inv = Inventory.objects.create(name='foo', organization=org1)

    u1 = permission_registry.user_model.objects.create(username='u1')
    u2 = permission_registry.user_model.objects.create(username='u2')
    u3 = permission_registry.user_model.objects.create(username='u3')

    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['change_organization', 'view_organization'],
        name='change-org',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    change_1 = rd.give_permission(u1, org1)
    change_2 = rd.give_permission(u2, org2)

    view_rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['view_organization', 'view_inventory'],
        name='view-inv-org',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    view_1 = view_rd.give_permission(u2, org1)
    assert u2.has_obj_perm(inv, 'view')

    inv_view, _ = RoleDefinition.objects.get_or_create(
        permissions=['view_inventory'], name='view-inv', content_type=permission_registry.content_type_model.objects.get_for_model(inv)
    )
    inv_1 = inv_view.give_permission(u3, inv)

    # u1 can see org1
    assert set(ObjectRole.visible_items(u1)) == set([change_1.object_role, view_1.object_role])
    assert set(RoleUserAssignment.visible_items(u1)) == set([change_1, view_1])

    # u2 can see org1, org2, and the inventory
    assert set(ObjectRole.visible_items(u2)) == set([change_1.object_role, change_2.object_role, view_1.object_role, inv_1.object_role])
    assert set(RoleUserAssignment.visible_items(u2)) == set([change_1, change_2, view_1, inv_1])

    # u3 can only see the inventory, no orgs
    assert set(ObjectRole.visible_items(u3)) == set([inv_1.object_role])
    assert set(RoleUserAssignment.visible_items(u3)) == set([inv_1])


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS=['is_superuser'])
def test_superuser_can_do_anything(inventory):
    user = permission_registry.user_model.objects.create(username='superuser', is_superuser=True)
    assert user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS=[])
def test_superuser_flag_not_considered(inventory):
    user = permission_registry.user_model.objects.create(username='superuser', is_superuser=True)
    assert not user.has_obj_perm(inventory, 'change')


@pytest.mark.parametrize(
    'codename,expect',
    [
        ('change_inventory', False),
        ('add_inventory', True),
        ('lovely coconut', False),
        ('addition master', False),
        ('my_app.add_inventory', True),
        ('something.something.add_inventory', False),
    ],
)
def test_is_add_perm(codename, expect):
    assert is_add_perm(codename) is expect
