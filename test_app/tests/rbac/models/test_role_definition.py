from unittest import mock

import pytest
from django.db.utils import IntegrityError
from rest_framework.exceptions import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition, RoleEvaluation
from ansible_base.rbac.validators import validate_permissions_for_model
from test_app.models import ExampleEvent, Organization


@pytest.mark.django_db
def test_reuse_by_permission_list():
    demo_permissions = ['view_inventory', 'delete_inventory']
    rd1, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter')
    assert created

    # Will ignore name in favor of permissions
    rd2, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter-two')
    assert (not created) and (rd2 == rd1)


@pytest.mark.django_db
def test_reuse_by_permission_list_prefers_managed_role():
    permissions = ['view_inventory', 'delete_inventory']
    RoleDefinition.objects.create_from_permissions(permissions=permissions, name='custom-deleter')
    managed_rd = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='managed-deleter', managed=True)
    # A second, later-created managed role with the same permission set should not win over the first.
    RoleDefinition.objects.create_from_permissions(permissions=permissions, name='managed-deleter-two', managed=True)

    rd, created = RoleDefinition.objects.get_or_create(permissions=permissions, name='another-deleter')

    assert not created
    assert rd == managed_rd


@pytest.mark.django_db
def test_root_resource_add_invalid():
    with pytest.raises(ValidationError) as exc:
        org_admin, created = RoleDefinition.objects.get_or_create(
            name='org-view', permissions=['add_organization'], defaults={'content_type': DABContentType.objects.get_for_model(Organization)}
        )
    assert 'Permissions "add_organization" are not valid for organization roles' in str(exc)


@pytest.mark.django_db
def test_missing_view_permission():
    with pytest.raises(ValidationError) as exc:
        RoleDefinition.objects.create_from_permissions(
            permissions=['change_organization'], name='only-change-org', content_type=DABContentType.objects.get_for_model(Organization)
        )
    assert 'needs to include view' in str(exc)


@pytest.mark.django_db
def test_permission_for_unregistered_model():
    with pytest.raises(DABPermission.DoesNotExist):
        validate_permissions_for_model(
            permissions=[DABPermission.objects.get(codename='view_exampleevent')],
            content_type=DABContentType.objects.get_for_model(ExampleEvent),
        )


@pytest.mark.django_db
def test_other_models_immutable(organization, rando, org_inv_rd):
    org_inv_rd.give_permission(rando, organization)
    object_role = ObjectRole.objects.first()
    role_evaluation = RoleEvaluation.objects.first()
    with pytest.raises(RuntimeError):
        object_role.save()
    with pytest.raises(RuntimeError):
        role_evaluation.save()


@pytest.mark.django_db
def test_change_role_definition_permission(organization, team, inventory, member_rd, org_inv_rd):
    team_user = permission_registry.user_model.objects.create(username='team-user')
    org_user = permission_registry.user_model.objects.create(username='org-user')

    org_inv_rd.give_permission(team, organization)
    org_inv_rd.give_permission(org_user, organization)
    member_rd.give_permission(team_user, team)

    # sanity
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [False, False]

    new_perm = permission_registry.permission_qs.get(codename='update_inventory')
    org_inv_rd.permissions.add(new_perm)

    # Users get new permission
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [True, True]

    # Removing takes away the permission
    org_inv_rd.permissions.remove(new_perm)
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [False, False]


@pytest.mark.django_db
def test_change_role_definition_member_permission(organization, inventory, org_team_member_rd, member_rd, inv_rd):
    team_user = permission_registry.user_model.objects.create(username='team-user')
    org_team_user = permission_registry.user_model.objects.create(username='org-team-user')
    team = permission_registry.team_model.objects.create(name='ateam', organization=organization)
    org_team = permission_registry.team_model.objects.create(name='org-team', organization=organization)
    in_org_team = permission_registry.team_model.objects.create(name='child-team', organization=organization)

    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(team_user, team)

    org_team_member_rd.give_permission(org_team, organization)
    member_rd.give_permission(org_team_user, org_team)
    inv_rd.give_permission(in_org_team, inventory)

    # sanity
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]

    # Removing memberships takes away the permission
    member_perm = permission_registry.permission_qs.get(codename='member_team')
    member_rd.permissions.remove(member_perm)
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [False, False]

    # Adding it back restores them
    member_rd.permissions.add(member_perm)
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]


@pytest.mark.django_db
def test_clear_role_definition_member_permission(organization, inventory, org_team_member_rd, member_rd, inv_rd):
    """Clearing all permissions from a RoleDefinition that includes member_team
    correctly breaks team membership (exercises the post_clear branch in permissions_changed)."""
    team_user = permission_registry.user_model.objects.create(username='team-user')
    org_team_user = permission_registry.user_model.objects.create(username='org-team-user')
    team = permission_registry.team_model.objects.create(name='ateam', organization=organization)
    org_team = permission_registry.team_model.objects.create(name='org-team', organization=organization)
    in_org_team = permission_registry.team_model.objects.create(name='child-team', organization=organization)

    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(team_user, team)

    org_team_member_rd.give_permission(org_team, organization)
    member_rd.give_permission(org_team_user, org_team)
    inv_rd.give_permission(in_org_team, inventory)

    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]

    # Clear all permissions — triggers post_clear instead of post_remove
    member_rd.permissions.clear()
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [False, False]

    # Restoring the permission brings membership back
    member_perm = permission_registry.permission_qs.get(codename='member_team')
    member_rd.permissions.add(member_perm)
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]


@pytest.mark.django_db
def test_get_or_create_reuses_existing_role_by_name():
    """
    Test that get_or_create reuses an existing RoleDefinition when called
    with the same name. This tests the name-based lookup path through
    create_from_permissions() which uses Django's get_or_create internally.
    """
    permissions = ['view_inventory', 'change_inventory']

    # First call creates the RoleDefinition
    rd1, created1 = RoleDefinition.objects.get_or_create(permissions=permissions, name='test-role')
    assert created1 is True

    # Second call with SAME name should reuse existing (handled by create_from_permissions)
    rd2, created2 = RoleDefinition.objects.get_or_create(permissions=permissions, name='test-role')
    assert created2 is False
    assert rd2 == rd1

    # Verify only one RoleDefinition exists
    assert RoleDefinition.objects.filter(name='test-role').count() == 1


@pytest.mark.django_db
def test_get_or_create_with_defaults():
    """Test that get_or_create properly merges defaults into create kwargs."""
    permissions = ['view_inventory', 'change_inventory']
    content_type = DABContentType.objects.get_for_model(Organization)

    rd, created = RoleDefinition.objects.get_or_create(permissions=permissions, name='role-with-defaults', defaults={'content_type': content_type})

    assert created is True
    assert rd.content_type == content_type
    assert rd.name == 'role-with-defaults'


@pytest.mark.django_db
def test_get_or_create_without_permissions():
    """Test that get_or_create without permissions falls through to super()."""
    # When no permissions are provided, should use Django's default get_or_create
    rd, created = RoleDefinition.objects.get_or_create(name='no-permissions-role')

    assert created is True
    assert rd.name == 'no-permissions-role'
    assert rd.permissions.count() == 0

    # Calling again should return existing
    rd2, created2 = RoleDefinition.objects.get_or_create(name='no-permissions-role')

    assert created2 is False
    assert rd2 == rd


@pytest.mark.django_db
def test_get_or_create_reraises_integrity_error_after_max_retries():
    """
    Test that IntegrityError is re-raised after max retries are exhausted.

    This covers the edge case where IntegrityError keeps occurring and the
    retry loop cannot recover (e.g., database constraint violation unrelated
    to name uniqueness).
    """
    permissions = ['view_inventory', 'change_inventory']

    # Mock super().get_or_create to always raise IntegrityError
    # This simulates a persistent database error that can't be recovered
    with mock.patch.object(RoleDefinition.objects.__class__.__bases__[0], 'get_or_create', side_effect=IntegrityError('persistent database error')):
        with pytest.raises(IntegrityError):
            RoleDefinition.objects.get_or_create(permissions=permissions, name='will-fail')


@pytest.mark.django_db
def test_create_from_permissions_with_content_type_id():
    """
    Test that create_from_permissions correctly handles content_type_id parameter.

    This covers line 189-190 in role.py where content_type_id is looked up.
    """
    content_type = DABContentType.objects.get_for_model(Organization)

    # Use content_type_id instead of content_type
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'change_organization'], name='role-with-ct-id', content_type_id=content_type.id
    )

    assert rd.content_type == content_type
    assert rd.name == 'role-with-ct-id'


@pytest.mark.django_db
def test_create_from_permissions_reuses_existing_name():
    """
    Test that create_from_permissions reuses an existing RoleDefinition
    when a name collision occurs.

    This covers lines 195-199 in role.py where Django's get_or_create
    returns an existing record on name collision.
    """
    permissions = ['view_inventory', 'change_inventory']

    # First call creates the RoleDefinition
    rd1 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='collision-test-role')
    assert rd1 is not None

    # Second call with SAME name should reuse existing
    rd2 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='collision-test-role')
    assert rd2 == rd1

    # Verify only one RoleDefinition exists with this name
    assert RoleDefinition.objects.filter(name='collision-test-role').count() == 1
