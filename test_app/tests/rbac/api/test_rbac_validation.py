import pytest
from django.contrib.auth import get_user_model
from django.test.utils import override_settings
from django.urls import reverse

from ansible_base.lib.utils.auth import get_team_model
from ansible_base.rbac.models import RoleDefinition

Team = get_team_model()
User = get_user_model()


@pytest.mark.django_db
class TestSharedAssignmentsDisabled:
    NON_LOCAL_MESSAGE = 'Not managed locally, use the resource server instead'

    @override_settings(ALLOW_LOCAL_RESOURCE_MANAGEMENT=False)
    def test_team_member_role_not_assignable(self, member_rd, team, rando, admin_api_client):
        url = reverse('roleuserassignment-list')
        response = admin_api_client.post(url, data={'object_id': team.id, 'role_definition': member_rd.id, 'user': rando.id})
        assert response.status_code == 400, response.data
        assert self.NON_LOCAL_MESSAGE in str(response.data)

    @override_settings(ALLOW_LOCAL_RESOURCE_MANAGEMENT=False)
    def test_custom_roles_for_shared_stuff_not_allowed(self, admin_api_client):
        url = reverse('roledefinition-list')
        response = admin_api_client.post(
            url,
            data={
                'name': 'Alternative Organization Admin Role in Local Server',
                'content_type': 'aap.organization',
                'permissions': ['aap.view_organization', 'local.change_organization'],
            },
        )
        assert response.status_code == 400, response.data
        assert self.NON_LOCAL_MESSAGE in str(response.data)

    @override_settings(ALLOW_LOCAL_RESOURCE_MANAGEMENT=False)
    def test_resource_roles_still_assignable(self, org_inv_rd, organization, rando, admin_api_client):
        url = reverse('roleuserassignment-list')
        response = admin_api_client.post(url, data={'object_id': organization.id, 'role_definition': org_inv_rd.id, 'user': rando.id})
        assert response.status_code == 201, response.data

    @override_settings(ALLOW_LOCAL_RESOURCE_MANAGEMENT=False)
    def test_org_resource_roles_creatable(self, admin_api_client):
        url = reverse('roledefinition-list')
        # This only contains shared view_organization, which is necessary to create custom org-level roles for child resources
        response = admin_api_client.post(
            url,
            data={
                'name': 'Custom Organization Inventory Admin Role',
                'content_type': 'aap.organization',
                'permissions': ['aap.view_organization', 'local.change_inventory', 'local.view_inventory'],
            },
        )
        assert response.status_code == 201, response.data


@pytest.mark.django_db
@pytest.mark.parametrize("method", ['delete', 'patch'])
def test_cannot_modify_managed_role_definition(admin_api_client, method):
    rd = RoleDefinition.objects.create(name='foo role', managed=True)
    url = reverse('roledefinition-detail', kwargs={'pk': rd.pk})
    if method == 'delete':
        response = admin_api_client.delete(url)
    else:
        response = admin_api_client.patch(url, data={'description': 'foo'})
    assert response.status_code == 400, response.data
    assert 'Role is managed by the system' in response.data


@pytest.mark.django_db
def test_assignments_are_immutable(admin_api_client, rando, inventory, inv_rd):
    assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = admin_api_client.patch(url, data={'object_id': 2})
    assert response.status_code == 405


@pytest.mark.django_db
def test_permission_does_not_exist(admin_api_client):
    url = reverse('roledefinition-list')
    response = admin_api_client.post(url, data={'name': 'foo', 'permissions': ['foo.foo_foooo'], 'content_type': 'aap.inventory'})
    assert response.status_code == 400
    assert 'object does not exist' in str(response.data['permissions'][0])


@pytest.mark.django_db
def test_using_permission_for_wrong_model(admin_api_client):
    url = reverse('roledefinition-list')
    response = admin_api_client.post(url, data={'name': 'foo', 'permissions': ['aap.view_inventory'], 'content_type': 'aap.namespace'})
    assert response.status_code == 400
    assert 'Permissions "view_inventory" are not valid for namespace roles' in str(response.data['permissions'])


# NOTE: testing a null content_type seems to have a problem with render of admin_api_client
# this does not seem to be a problem when testing with a live server


@pytest.mark.django_db
def test_no_double_assignment(admin_api_client, rando, inventory, inv_rd):
    url = reverse('roleuserassignment-list')
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': rando.id, 'role_definition': inv_rd.id})
    assert response.status_code == 201
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': rando.id, 'role_definition': inv_rd.id})
    assert response.status_code == 201


@pytest.mark.django_db
def test_can_not_give_global_role_to_obj(admin_api_client, rando, inventory, global_inv_rd):
    url = reverse('roleuserassignment-list')
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': rando.id, 'role_definition': global_inv_rd.id})
    assert response.status_code == 400, response.data
    assert 'System role does not allow for object assignment' in str(response.data['object_id'])


@pytest.mark.django_db
def test_can_not_make_global_role_with_member_permission(admin_api_client):
    url = reverse('roledefinition-list')
    response = admin_api_client.post(
        url, data={'name': 'foo', 'permissions': ['shared.view_organization', 'shared.view_team', 'shared.member_team'], 'content_type': ''}
    )
    assert response.status_code == 400
    assert 'member_team permission can not be used in global roles' in str(response.data['permissions'])


@pytest.mark.django_db
def test_callback_validate_role_user_assignment(admin_api_client, inventory, inv_rd):
    url = reverse('roleuserassignment-list')
    user = User.objects.create(username='user-allowed')
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': user.id, 'role_definition': inv_rd.id})
    assert response.status_code == 201

    user = User.objects.create(username='test-400')
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': user.id, 'role_definition': inv_rd.id})
    assert response.status_code == 400
    assert "Role assignment not allowed 400" in str(response.data)

    user = User.objects.create(username='test-403')
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'user': user.id, 'role_definition': inv_rd.id})
    assert response.status_code == 403
    assert "Role assignment not allowed 403" in str(response.data)


@pytest.mark.django_db
def test_callback_validate_role_team_assignment(admin_api_client, inventory, organization, inv_rd):
    url = reverse('roleteamassignment-list')
    team = Team.objects.create(name='team-allowed', organization=organization)
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'team': team.id, 'role_definition': inv_rd.id})
    assert response.status_code == 201

    team = Team.objects.create(name='test-400', organization=organization)
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'team': team.id, 'role_definition': inv_rd.id})
    assert response.status_code == 400
    assert "Role assignment not allowed 400" in str(response.data)

    team = Team.objects.create(name='test-403', organization=organization)
    response = admin_api_client.post(url, data={'object_id': inventory.id, 'team': team.id, 'role_definition': inv_rd.id})
    assert response.status_code == 403
    assert "Role assignment not allowed 403" in str(response.data)
