from unittest import mock

import pytest
from django.apps import apps
from django.test.utils import override_settings

from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleEvaluation, RoleUserAssignment
from test_app.models import User

INVENTORY_OBJ_PERMS = ('change_inventory', 'update_inventory', 'view_inventory', 'delete_inventory')


@pytest.mark.django_db
def test_create_inventory_gain_role(rando, inventory):
    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set()
    RoleDefinition.objects.give_creator_permissions(rando, inventory)
    assert set(perm_name.split('_', 1)[0] for perm_name in RoleEvaluation.get_permissions(rando, inventory)) == {'change', 'delete', 'view'}
    assert RoleDefinition.objects.filter(name='inventory-creator-permission').exists()


@pytest.mark.django_db
def test_create_inventory_already_has_role(rando, inventory):
    org_inv_rd = RoleDefinition.objects.create_from_permissions(
        name='global-inventory-admin', permissions=INVENTORY_OBJ_PERMS, content_type=DABContentType.objects.get_for_model(inventory.organization)
    )
    org_assignment = org_inv_rd.give_permission(rando, inventory.organization)
    # User should already have (at least) all object permissions on the inventory
    assert not (set(INVENTORY_OBJ_PERMS) - set(RoleEvaluation.get_permissions(rando, inventory)))
    RoleDefinition.objects.give_creator_permissions(rando, inventory)
    assert set(rando.has_roles.all()) == {org_assignment.object_role}


@pytest.mark.django_db
def test_creator_permissions_for_superuser(inventory):
    admin_user = User.objects.create(is_superuser=True, username='admin')
    RoleDefinition.objects.give_creator_permissions(admin_user, inventory)
    assert not admin_user.has_roles.exists()


@pytest.mark.django_db
def test_creator_permissions_for_organization(organization, inventory, rando):
    "This is necessary if someone were to use add_organization permission system level"
    RoleDefinition.objects.give_creator_permissions(rando, organization)
    assert rando.has_obj_perm(organization, 'change_organization')
    assert rando.has_obj_perm(organization, 'add_inventory')
    assert rando.has_obj_perm(organization, 'add_namespace')
    assert rando.has_obj_perm(organization, 'add_collectionimport')
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_no_creator_assignment_with_system_perms(rando, inventory):
    rd = RoleDefinition.objects.create_from_permissions(name='global-inventory-admin', permissions=INVENTORY_OBJ_PERMS)
    rd.give_global_permission(rando)
    RoleDefinition.objects.give_creator_permissions(rando, inventory)
    assert not rando.has_roles.exists()


@pytest.mark.django_db
def test_custom_creation_perms(rando, inventory):
    # these settings would not let users delete what they create
    # which someone might want, you do you
    with override_settings(ANSIBLE_BASE_CREATOR_DEFAULTS=['change', 'view']):
        RoleDefinition.objects.give_creator_permissions(rando, inventory)
        assert set(perm_name.split('_', 1)[0] for perm_name in RoleEvaluation.get_permissions(rando, inventory)) == {'change', 'view'}


@pytest.mark.django_db
def test_creator_permission_for_unregistered_model(rando):
    prior_ct = DABContentType.objects.count()
    prior_assignments = RoleUserAssignment.objects.count()
    prior_rds = RoleDefinition.objects.count()

    cls = apps.get_model('test_app.secretcolor')
    obj = cls.objects.create()
    RoleDefinition.objects.give_creator_permissions(rando, obj)  # should do nothing

    assert DABContentType.objects.count() == prior_ct  # did not create anything
    assert RoleUserAssignment.objects.count() == prior_assignments
    assert RoleDefinition.objects.count() == prior_rds


@pytest.mark.django_db
def test_creator_permission_does_reverse_sync(rando, inventory):
    # mock maybe_reverse_sync_assignment
    with mock.patch('ansible_base.rbac.models.role.maybe_reverse_sync_assignment') as mock_maybe_reverse_sync_assignment:
        RoleDefinition.objects.give_creator_permissions(rando, inventory)
        mock_maybe_reverse_sync_assignment.assert_called_once()
        RoleDefinition.objects.give_creator_permissions(rando, inventory)
        # assert mock was not called another time
        mock_maybe_reverse_sync_assignment.assert_called_once()


@pytest.mark.django_db
def test_give_creator_permissions_handles_race(rando, inventory):
    """
    Test that concurrent give_creator_permissions calls don't fail when racing
    to create the same creator-permission RoleDefinition. This simulates the scenario
    where multiple users create objects (e.g., projects) simultaneously in the
    same organization.

    The implementation uses Django's get_or_create() which handles race conditions
    internally via a get-create-get pattern.
    """
    # First call succeeds normally, creating the creator-permission RoleDefinition
    RoleDefinition.objects.give_creator_permissions(rando, inventory)

    # Create another user who will also create an inventory
    user2 = User.objects.create(username='user2')

    # Second call should reuse the existing RoleDefinition (no race condition error)
    RoleDefinition.objects.give_creator_permissions(user2, inventory)

    # Verify only one RoleDefinition exists with the creator-permission name
    assert RoleDefinition.objects.filter(name='inventory-creator-permission').count() == 1

    # Verify both users got permissions through the same role
    assert rando.has_obj_perm(inventory, 'change')
    assert rando.has_obj_perm(inventory, 'view')
    assert user2.has_obj_perm(inventory, 'change')
    assert user2.has_obj_perm(inventory, 'view')
