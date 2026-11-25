import pytest
from django.test.utils import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import ImmutableTask, Inventory, Organization, ResourceWithAdminPerm


@pytest.fixture
def task_admin_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask', 'delete_immutabletask', 'cancel_immutabletask'],
        name='Task Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )


@pytest.fixture
def task_view_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask'],
        name='Task View',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )


@pytest.mark.django_db
def test_create_user_assignment_immutable(user_api_client, user, rando, task_admin_rd, task_view_rd, org_admin_rd, organization):
    task = ImmutableTask.objects.create()
    org_admin_rd.give_permission(user, organization)  # setup so that user can see rando
    url = get_relative_url('roleuserassignment-list')
    request_data = {"user": rando.pk, "role_definition": task_admin_rd.pk, "object_id": task.pk}

    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 400, response.data
    assert 'object does not exist' in response.data['object_id'][0]

    task_view_rd.give_permission(user, task)
    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 403, response.data
    # Test custom error message
    assert 'You do not have cancel_immutabletask permission' in str(response.data)

    task_admin_rd.give_permission(user, task)
    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_remove_user_assignment_immutable(user_api_client, user, rando, task_admin_rd, task_view_rd):
    task = ImmutableTask.objects.create()
    assignment = task_admin_rd.give_permission(rando, task)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})

    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    task_view_rd.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 403, response.data
    # Test custom error message
    assert 'You do not have cancel_immutabletask permission' in str(response.data)

    task_admin_rd.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_user_assignment_with_global_role(user_api_client, user, inv_rd, global_inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_global_role_assignment(user_api_client, admin_api_client, user, global_inv_rd, rando):
    assignment = global_inv_rd.give_global_permission(rando)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    # Having the role itself does not give permission to remove assignments, but this user can view
    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 403, response.data

    # Only superuser can remove global assignments
    response = admin_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_global_assignment_yourself(user_api_client, global_inv_rd, user, inventory):
    assert not user.has_obj_perm(inventory, 'change')

    assignment = global_inv_rd.give_global_permission(user)
    assert user.has_obj_perm(inventory, 'change')

    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    # Manually delete cache, because view operates on a User instance loaded anew from DB
    delattr(user, '_singleton_permissions')
    assert response.status_code == 204, response.data
    assert not user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_remove_object_assignment_yourself(user_api_client, user, inventory):
    assert not user.has_obj_perm(inventory, 'view')

    rd = RoleDefinition.objects.create_from_permissions(
        name='inventory viewer role', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(inventory)
    )
    assignment = rd.give_permission(user, inventory)
    assert user.has_obj_perm(inventory, 'view')

    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data
    assert not user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
class TestManagePermissionAction:
    """Tests for ANSIBLE_BASE_MANAGE_PERMISSION_ACTION controlling who can assign roles"""

    def test_change_user_can_assign_default(self, user_api_client, user, rando, inv_rd, org_admin_rd, organization):
        """With default setting ('change'), user with change permission can assign roles"""
        org_admin_rd.give_permission(user, organization)
        inv_rd.give_permission(user, Inventory.objects.create(name='test-inv', organization=organization))
        inv = Inventory.objects.create(name='target-inv', organization=organization)
        inv_rd.give_permission(user, inv)

        url = get_relative_url('roleuserassignment-list')
        view_rd = RoleDefinition.objects.create_from_permissions(
            name='view-inv', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(Inventory)
        )
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 201, response.data

    @override_settings(ANSIBLE_BASE_MANAGE_PERMISSION_ACTION=None)
    def test_all_permissions_required_when_setting_none(self, user_api_client, user, rando, org_admin_rd, organization):
        """With setting=None, user needs ALL permissions to assign roles"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        inv = Inventory.objects.create(name='target-inv', organization=other_org)

        view_rd = RoleDefinition.objects.create_from_permissions(
            name='view-inv', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(Inventory)
        )
        # Give user only view — not enough when all permissions required
        view_rd.give_permission(user, inv)
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 403, response.data

        # Give user all permissions — now assignment succeeds
        all_rd = RoleDefinition.objects.create_from_permissions(
            name='all-inv',
            permissions=['change_inventory', 'delete_inventory', 'view_inventory', 'update_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        all_rd.give_permission(user, inv)
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 201, response.data

    @override_settings(ANSIBLE_BASE_MANAGE_PERMISSION_ACTION='administrate')
    def test_administrate_action_controls_assignment(self, user_api_client, user, rando, org_admin_rd, organization):
        """With setting='administrate', only users with 'administrate' permission can assign roles"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        resource = ResourceWithAdminPerm.objects.create(name='test-resource', organization=other_org)

        admin_perm_rd = RoleDefinition.objects.create_from_permissions(
            name='admin-resource',
            permissions=[
                'administrate_resourcewithadminperm',
                'change_resourcewithadminperm',
                'delete_resourcewithadminperm',
                'view_resourcewithadminperm',
            ],
            content_type=permission_registry.content_type_model.objects.get_for_model(ResourceWithAdminPerm),
        )
        change_rd = RoleDefinition.objects.create_from_permissions(
            name='change-resource',
            permissions=['change_resourcewithadminperm', 'view_resourcewithadminperm'],
            content_type=permission_registry.content_type_model.objects.get_for_model(ResourceWithAdminPerm),
        )
        view_rd = RoleDefinition.objects.create_from_permissions(
            name='view-resource',
            permissions=['view_resourcewithadminperm'],
            content_type=permission_registry.content_type_model.objects.get_for_model(ResourceWithAdminPerm),
        )

        # User with change but NOT administrate cannot assign roles
        change_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data

        # User with administrate CAN assign roles
        admin_perm_rd.give_permission(user, resource)
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

    @override_settings(ANSIBLE_BASE_MANAGE_PERMISSION_ACTION='administrate')
    def test_model_without_manage_action_requires_all(self, user_api_client, user, rando, org_admin_rd, organization):
        """Models without the configured manage action fall back to requiring all permissions"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        inv = Inventory.objects.create(name='target-inv', organization=other_org)

        change_rd = RoleDefinition.objects.create_from_permissions(
            name='change-inv',
            permissions=['change_inventory', 'view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        view_rd = RoleDefinition.objects.create_from_permissions(
            name='view-inv',
            permissions=['view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )

        # Inventory has no 'administrate' permission, so falls back to "all permissions required"
        # User with change only cannot assign
        change_rd.give_permission(user, inv)
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 403, response.data

    def test_cannot_assign_role_with_permissions_user_lacks(self, user_api_client, user, rando, org_admin_rd, organization):
        """User with change+view cannot assign a role containing update, which they lack"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        inv = Inventory.objects.create(name='target-inv', organization=other_org)

        change_view_rd = RoleDefinition.objects.create_from_permissions(
            name='change-view-inv',
            permissions=['change_inventory', 'view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        update_rd = RoleDefinition.objects.create_from_permissions(
            name='update-inv',
            permissions=['update_inventory', 'view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )

        change_view_rd.give_permission(user, inv)
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': update_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 403, response.data
        assert 'update_inventory' in str(response.data)

    def test_can_assign_role_with_subset_of_permissions(self, user_api_client, user, rando, org_admin_rd, organization):
        """User with change+view+update can assign a role containing only view"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        inv = Inventory.objects.create(name='target-inv', organization=other_org)

        all_rd = RoleDefinition.objects.create_from_permissions(
            name='all-inv',
            permissions=['change_inventory', 'view_inventory', 'update_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        view_rd = RoleDefinition.objects.create_from_permissions(
            name='view-inv',
            permissions=['view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )

        all_rd.give_permission(user, inv)
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 201, response.data

    def test_escalation_blocked_even_with_manage_permission(self, user_api_client, user, rando, org_admin_rd, organization):
        """User with change (the gate) but not update cannot assign a role with update — escalation blocked"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='other-org')
        inv = Inventory.objects.create(name='target-inv', organization=other_org)

        change_view_rd = RoleDefinition.objects.create_from_permissions(
            name='change-view-inv',
            permissions=['change_inventory', 'view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        escalation_rd = RoleDefinition.objects.create_from_permissions(
            name='change-update-inv',
            permissions=['change_inventory', 'update_inventory', 'view_inventory'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )

        # User has the gate (change) but not update
        change_view_rd.give_permission(user, inv)
        url = get_relative_url('roleuserassignment-list')

        # Can assign the role they have (change+view) — no escalation
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': change_view_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 201, response.data

        # Cannot assign the role with extra permissions they lack
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': escalation_rd.pk, 'object_id': inv.pk})
        assert response.status_code == 403, response.data
        assert 'update_inventory' in str(response.data)


@pytest.mark.django_db
class TestEscalationWithCustomActions:
    """Tests for escalation prevention using ResourceWithAdminPerm with bop and twist custom actions.

    ResourceWithAdminPerm has: add, change, delete, view (defaults) + administrate, bop, twist (custom).
    These tests verify that users can only assign roles containing permissions they actually hold.
    """

    @pytest.fixture
    def resource_ct(self):
        return permission_registry.content_type_model.objects.get_for_model(ResourceWithAdminPerm)

    @pytest.fixture
    def setup_user_with_org_visibility(self, user, org_admin_rd, organization):
        """Give user org admin so they can see other users, but create resources in a separate org"""
        org_admin_rd.give_permission(user, organization)
        other_org = Organization.objects.create(name='escalation-test-org')
        return other_org

    def _make_rd(self, name, permissions, resource_ct):
        return RoleDefinition.objects.create_from_permissions(
            name=name,
            permissions=permissions,
            content_type=resource_ct,
        )

    def test_has_bop_can_assign_bop_not_twist(self, user_api_client, user, rando, resource_ct, setup_user_with_org_visibility):
        """User with change+bop can assign bop but not twist"""
        other_org = setup_user_with_org_visibility
        resource = ResourceWithAdminPerm.objects.create(name='r1', organization=other_org)

        user_rd = self._make_rd('user-perms', ['change_resourcewithadminperm', 'bop_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        bop_rd = self._make_rd('bop-role', ['bop_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        twist_rd = self._make_rd('twist-role', ['twist_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        user_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': bop_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': twist_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data
        assert 'twist_resourcewithadminperm' in str(response.data)

    def test_has_both_can_assign_both(self, user_api_client, user, rando, resource_ct, setup_user_with_org_visibility):
        """User with change+bop+twist can assign a role containing both bop and twist"""
        other_org = setup_user_with_org_visibility
        resource = ResourceWithAdminPerm.objects.create(name='r1', organization=other_org)

        user_rd = self._make_rd(
            'user-perms',
            ['change_resourcewithadminperm', 'bop_resourcewithadminperm', 'twist_resourcewithadminperm', 'view_resourcewithadminperm'],
            resource_ct,
        )
        both_rd = self._make_rd('both-role', ['bop_resourcewithadminperm', 'twist_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        user_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': both_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

    def test_has_neither_cannot_assign_either(self, user_api_client, user, rando, resource_ct, setup_user_with_org_visibility):
        """User with change but no bop or twist cannot assign either"""
        other_org = setup_user_with_org_visibility
        resource = ResourceWithAdminPerm.objects.create(name='r1', organization=other_org)

        user_rd = self._make_rd('user-perms', ['change_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        bop_rd = self._make_rd('bop-role', ['bop_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        twist_rd = self._make_rd('twist-role', ['twist_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        user_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': bop_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data
        assert 'bop_resourcewithadminperm' in str(response.data)

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': twist_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data
        assert 'twist_resourcewithadminperm' in str(response.data)

    def test_can_still_assign_crud_without_custom_actions(self, user_api_client, user, rando, resource_ct, setup_user_with_org_visibility):
        """User with change but no bop/twist can still assign CRUD-only roles"""
        other_org = setup_user_with_org_visibility
        resource = ResourceWithAdminPerm.objects.create(name='r1', organization=other_org)

        user_rd = self._make_rd('user-perms', ['change_resourcewithadminperm', 'delete_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        crud_rd = self._make_rd('crud-role', ['change_resourcewithadminperm', 'delete_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        user_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': crud_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

    def test_no_change_cannot_assign_anything(self, user_api_client, user, rando, resource_ct, setup_user_with_org_visibility):
        """User without change permission (the gate) cannot assign any roles"""
        other_org = setup_user_with_org_visibility
        resource = ResourceWithAdminPerm.objects.create(name='r1', organization=other_org)

        view_only_rd = self._make_rd('view-only', ['view_resourcewithadminperm'], resource_ct)
        bop_rd = self._make_rd('bop-role', ['bop_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        view_only_rd.give_permission(user, resource)
        url = get_relative_url('roleuserassignment-list')

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_only_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': bop_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data

    def test_creator_gets_crud_then_delegates(self, user_api_client, user, rando, resource_ct, org_admin_rd, organization):
        """Full-cycle: user gets add on org, creates object, gets creator CRUD, can delegate CRUD but not bop/twist"""
        # Use a separate org so org_admin on `organization` only provides user visibility (see rando)
        creator_org = Organization.objects.create(name='creator-org')
        org_admin_rd.give_permission(user, organization)

        add_org_rd = RoleDefinition.objects.create_from_permissions(
            name='org-add-resource',
            permissions=['add_resourcewithadminperm', 'view_organization'],
            content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        )
        add_org_rd.give_permission(user, creator_org)

        resource = ResourceWithAdminPerm.objects.create(name='created-resource', organization=creator_org)
        RoleDefinition.objects.give_creator_permissions(user, resource)

        view_rd = self._make_rd('view-role', ['view_resourcewithadminperm'], resource_ct)
        change_view_rd = self._make_rd('change-view-role', ['change_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        bop_rd = self._make_rd('bop-role', ['bop_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)
        twist_rd = self._make_rd('twist-role', ['twist_resourcewithadminperm', 'view_resourcewithadminperm'], resource_ct)

        url = get_relative_url('roleuserassignment-list')

        # Creator has CRUD (add excluded at object-level), so can assign view and change
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': view_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': change_view_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 201, response.data

        # Creator does NOT have bop or twist — cannot delegate them
        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': bop_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data
        assert 'bop_resourcewithadminperm' in str(response.data)

        response = user_api_client.post(url, data={'user': rando.pk, 'role_definition': twist_rd.pk, 'object_id': resource.pk})
        assert response.status_code == 403, response.data
        assert 'twist_resourcewithadminperm' in str(response.data)
