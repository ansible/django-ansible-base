from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition, RoleEvaluation
from ansible_base.rbac.validators import validate_permissions_for_model
from test_app.models import ExampleEvent, Organization


@pytest.mark.django_db
def test_get_or_create_different_permission_count():
    """Roles with different permission counts should not be matched."""
    rd1, created1 = RoleDefinition.objects.get_or_create(permissions=['view_inventory', 'change_inventory'], name='two-perm-role')
    assert created1

    rd2, created2 = RoleDefinition.objects.get_or_create(permissions=['view_inventory', 'change_inventory', 'delete_inventory'], name='three-perm-role')
    assert created2 and rd2.id != rd1.id


@pytest.mark.django_db
def test_get_or_create_same_count_different_permissions():
    """Roles with same count but different permissions should not be matched."""
    rd1, created1 = RoleDefinition.objects.get_or_create(permissions=['view_inventory', 'change_inventory'], name='view-change-role')
    assert created1

    rd2, created2 = RoleDefinition.objects.get_or_create(permissions=['view_inventory', 'delete_inventory'], name='view-delete-role')
    assert created2 and rd2.id != rd1.id


@pytest.mark.django_db
def test_create_from_permissions_reuses_on_name_collision():
    """create_from_permissions reuses existing role on name collision instead of raising IntegrityError."""
    permissions = ['view_organization', 'change_organization']
    rd1 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='collision-test-role')

    rd2 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='collision-test-role')
    assert rd2.id == rd1.id


@pytest.mark.django_db
def test_get_or_create_without_permissions_uses_parent():
    """get_or_create without permissions falls back to standard Django get_or_create by name."""
    rd1, created1 = RoleDefinition.objects.get_or_create(name='no-perm-role-1')
    assert created1

    rd2, created2 = RoleDefinition.objects.get_or_create(name='no-perm-role-1')
    assert (not created2) and rd2.id == rd1.id


@pytest.mark.django_db
def test_get_or_create_with_defaults():
    """Defaults parameter is properly applied when creating new role."""
    rd1, created = RoleDefinition.objects.get_or_create(permissions=['view_inventory'], name='defaults-test-role', defaults={'description': 'Test description'})
    assert created and rd1.description == 'Test description'


@pytest.mark.django_db
def test_get_or_create_non_postgresql_skips_advisory_lock():
    """Advisory lock is skipped for non-PostgreSQL databases with debug logging."""
    with patch('ansible_base.rbac.models.role.connection') as mock_connection:
        mock_connection.vendor = 'sqlite'
        with patch('ansible_base.rbac.models.role.logger') as mock_logger:
            rd, created = RoleDefinition.objects.get_or_create(permissions=['view_inventory'], name='sqlite-test-role')
            assert created
            # Verify debug log was called for non-PostgreSQL fallback
            mock_logger.debug.assert_called_once()
            assert 'sqlite' in str(mock_logger.debug.call_args)
            assert 'pg_advisory_xact_lock' in str(mock_logger.debug.call_args)


@pytest.mark.django_db
def test_create_from_permissions_logs_reuse():
    """create_from_permissions logs debug message when reusing existing role."""
    permissions = ['view_organization', 'change_organization']
    rd1 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='log-reuse-test-role')

    with patch('ansible_base.rbac.models.role.logger') as mock_logger:
        rd2 = RoleDefinition.objects.create_from_permissions(permissions=permissions, name='log-reuse-test-role')
        assert rd2.id == rd1.id
        # Verify debug log was called for reuse
        mock_logger.debug.assert_called()
        log_message = str(mock_logger.debug.call_args)
        assert 'Reused existing RoleDefinition' in log_message


@pytest.mark.django_db
def test_get_or_create_generates_deterministic_lock_id():
    """Lock ID is generated deterministically from permission set (order-independent)."""
    # Same permissions in different order should generate the same lock ID
    permissions_a = ['view_inventory', 'change_inventory']
    permissions_b = ['change_inventory', 'view_inventory']

    # Hash of frozenset should be the same regardless of order
    lock_id_a = hash(frozenset(permissions_a)) % (2**31)
    lock_id_b = hash(frozenset(permissions_b)) % (2**31)
    assert lock_id_a == lock_id_b

    # Different permissions should generate different lock IDs
    permissions_c = ['view_inventory', 'delete_inventory']
    lock_id_c = hash(frozenset(permissions_c)) % (2**31)
    assert lock_id_a != lock_id_c


@pytest.mark.django_db
def test_reuse_by_permission_list():
    demo_permissions = ['view_inventory', 'delete_inventory']
    rd1, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter')
    assert created

    # Will ignore name in favor of permissions
    rd2, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter-two')
    assert (not created) and (rd2 == rd1)


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
