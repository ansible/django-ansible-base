import pytest
from django.test.utils import override_settings

from ansible_base.lib.utils.response import get_relative_url
from test_app.models import Inventory, User


@pytest.mark.django_db
class TestRoleDefinitions:
    def test_patch_system_role(self, admin_api_client, global_inv_rd):
        "Making a PATCH to a system role should not re-validate the content_type"
        url = get_relative_url('roledefinition-detail', kwargs={'pk': global_inv_rd.pk})
        response = admin_api_client.patch(url, data={'name': 'my new name'})
        assert response.status_code == 200
        global_inv_rd.refresh_from_db()
        assert global_inv_rd.name == 'my new name'
        assert global_inv_rd.content_type is None
        assert response.data['content_type'] is None

    @override_settings(ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API=False)
    def test_patch_object_role(self, admin_api_client, inv_rd):
        "Making a PATCH to a system role should not re-validate the content_type"
        url = get_relative_url('roledefinition-detail', kwargs={'pk': inv_rd.pk})
        response = admin_api_client.patch(url, data={'name': 'my new name'})
        assert response.status_code == 200
        inv_rd.refresh_from_db()
        assert inv_rd.name == 'my new name'
        assert inv_rd.content_type.model == 'inventory'
        assert response.data['content_type'] == 'aap.inventory'

    def test_create_invalid_custom_system_role(self, admin_api_client):
        response = admin_api_client.post(
            get_relative_url('roledefinition-list'), data={'name': 'global inventory changer but not viewer', 'permissions': ['aap.change_inventory']}
        )
        assert response.status_code == 400, response.data
        assert 'Permissions for model inventory needs to include view' in str(response.data)

    def test_create_custom_system_role(self, admin_api_client):
        "Make a POST to create a custom role with system permissions"
        response = admin_api_client.post(
            get_relative_url('roledefinition-list'), data={'name': 'global inventory viewer', 'permissions': ['aap.view_inventory']}
        )
        assert response.status_code == 201, response.data
        assert response.data['permissions'] == ['aap.view_inventory']


@pytest.mark.django_db
class TestAssignmentPermission:
    @pytest.fixture
    def org_admin(self, user, organization, org_admin_rd):
        "Organization admin is commonly needed because with default settings they can view all users"
        org_admin_rd.give_permission(user, organization)
        return user

    @pytest.fixture
    def inventory_2(self, organization_2):
        "Inventory unrelated to organization fixture so we can test isolated permissions"
        return Inventory.objects.create(name='inventory-2', organization=organization_2)

    def test_object_permission_needed(self, inventory_2, inv_rd, org_admin, user_api_client, view_inv_rd):
        url = get_relative_url('roleuserassignment-list')
        rando = User.objects.create(username='rando')
        create_data = {'object_id': inventory_2.id, 'user': rando.id, 'role_definition': inv_rd.id}

        # user can not determine inventory object exists because they have no permissions to it
        assert not org_admin.has_obj_perm(inventory_2, 'view')  # sanity
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 400
        assert not rando.has_obj_perm(inventory_2, 'change')
        assert 'object does not exist' in response.data['object_id'][0]

        # user can not give inventory object permission because they have do not have change permission
        view_inv_rd.give_permission(org_admin, inventory_2)
        assert not org_admin.has_obj_perm(inventory_2, 'change')  # sanity
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 403
        assert not rando.has_obj_perm(inventory_2, 'change')

        # After giving user admin to inventory, user can delegate that permission to others
        inv_rd.give_permission(org_admin, inventory_2)
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 201
        assert rando.has_obj_perm(inventory_2, 'change')

    def test_object_not_found(self, inv_rd, org_admin, user_api_client):
        url = get_relative_url('roleuserassignment-list')
        rando = User.objects.create(username='rando')
        create_data = {'object_id': 123456, 'user': rando.id, 'role_definition': inv_rd.id}

        # Expect 400 error in cases where _related_ object is not found
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 400
        print(response.data)
        assert 'object does not exist' in response.data['object_id'][0]

    def test_user_not_found(self, inv_rd, inventory, org_admin, user_api_client):
        url = get_relative_url('roleuserassignment-list')
        create_data = {'object_id': inventory.id, 'user': 123456, 'role_definition': inv_rd.id}

        # Expect 400 error in cases where _related_ object is not found
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 400
        assert 'object does not exist' in response.data['user'][0]
