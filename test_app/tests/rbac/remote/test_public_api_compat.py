import uuid

import pytest

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABPermission, RoleDefinition, RoleUserAssignment
from ansible_base.rbac.remote import RemoteObject
from ansible_base.rbac.service_api.serializers import ServiceRoleUserAssignmentSerializer
from test_app.models import Organization

# Role Definitions


@pytest.mark.django_db
def test_role_definition_list_remote_and_local(admin_api_client, inv_rd, foo_rd):
    "Test that the role_definitions endpoint does not choke when remote permissions are listed."
    url = get_relative_url('roledefinition-list')
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['next'] is None  # sanity, will mess up test if there are more pages
    rd_by_name = {rd['name']: rd for rd in response.data['results']}
    assert inv_rd.name in rd_by_name
    assert foo_rd.name in rd_by_name
    # Assertion coppied from API test test_get_role_definition
    assert set(rd_by_name[inv_rd.name]['permissions']) == set(['aap.change_inventory', 'aap.view_inventory'])
    assert rd_by_name[foo_rd.name]['permissions'] == ['foo.foo_foo']


@pytest.mark.django_db
def test_create_remote_role_definition_for_remote(admin_api_client, foo_type, foo_permission):
    "Test creation of a custom role definition that gives permission to remote things."
    url = get_relative_url("roledefinition-list")
    data = dict(name='foo-foo-foo-custom', description='bar', permissions=[foo_permission.api_slug], content_type=foo_type.api_slug)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['name'] == 'foo-foo-foo-custom'
    assert response.data['permissions'] == ['foo.foo_foo']


@pytest.mark.django_db
def test_create_remote_role_definition_global(admin_api_client, foo_permission):
    "Test creation of a system-wide role definition for a remote model"
    url = get_relative_url("roledefinition-list")
    data = dict(name='foo-foo-foo-global', description='bar', permissions=[foo_permission.api_slug], content_type=None)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['name'] == 'foo-foo-foo-global'
    assert response.data['permissions'] == ['foo.foo_foo']


@pytest.mark.django_db
def test_create_remote_role_definition_organization(admin_api_client, foo_permission):
    "Test creation of an organization-wide role definition for a remote model"
    url = get_relative_url("roledefinition-list")
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    data = dict(name='foo-foo-foo-org', description='bar', permissions=[foo_permission.api_slug, 'shared.view_organization'], content_type=org_ct.api_slug)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['name'] == 'foo-foo-foo-org'
    assert set(response.data['permissions']) == {'foo.foo_foo', 'shared.view_organization'}


# Role User Assignments


@pytest.mark.django_db
def test_user_role_assignment_remote_and_local(admin_api_client, rando, foo_type, foo_rd):
    "Test that after assigning permission to remote objects the assignment list works."
    a_foo = RemoteObject(content_type=foo_type, object_id=42)
    assignment = foo_rd.give_permission(rando, a_foo)
    assignment.content_object

    assert isinstance(assignment.content_object, RemoteObject)

    # Should show up in the assignments list
    url = get_relative_url('roleuserassignment-list')
    response = admin_api_client.get(url, format="json")
    assert response.status_code == 200, response.data

    data_by_rd = {item['role_definition']: item for item in response.data['results']}
    assert foo_rd.id in data_by_rd
    item = data_by_rd[foo_rd.id]
    assert item['user'] == rando.id
    assert item['object_id'] == str(a_foo.object_id)
    assert 'summary_fields' in item
    sf = item['summary_fields']
    assert 'content_object' in sf
    assert sf['content_object'] == {'<remote_object_placeholder>': True, 'model_name': 'foo', 'service': 'foo', 'pk': 42}


@pytest.mark.django_db
def test_give_permission_to_remote_object(admin_api_client, rando, foo_type, foo_rd):
    a_foo = RemoteObject(content_type=foo_type, object_id=42)
    assert not rando.has_obj_perm(a_foo, 'foo')

    url = get_relative_url('roleuserassignment-list')
    # NOTE: at this point the object_id is made up, cross-server coordination is not running here
    data = {"role_definition": foo_rd.id, "user": rando.pk, "object_id": 42}
    response = admin_api_client.post(path=url, data=data)
    assert response.status_code == 201, response.data

    assert rando.has_obj_perm(a_foo, 'foo')


@pytest.mark.django_db
def test_give_permission_to_remote_object_uuid(admin_api_client, rando, foo_type_uuid, foo_rd_uuid):
    pk_value = str(uuid.uuid4())
    a_foo = RemoteObject(content_type=foo_type_uuid, object_id=pk_value)
    assert not rando.has_obj_perm(a_foo, 'foo')

    url = get_relative_url('roleuserassignment-list')
    data = {"role_definition": foo_rd_uuid.id, "user": rando.pk, "object_id": pk_value}
    response = admin_api_client.post(path=url, data=data)
    assert response.status_code == 201, response.data
    assignment = RoleUserAssignment.objects.get(pk=response.data['id'])

    # Test that we can serialize the assignment in a GET
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    valid_items = [item for item in response.data['results'] if item['id'] == assignment.id]
    assert len(valid_items) == 1
    assignment_data = valid_items[0]
    assert 'content_object' in assignment_data['summary_fields']
    assert assignment_data['summary_fields']['content_object']['pk'] == str(a_foo.object_id)

    assert rando.has_obj_perm(a_foo, 'foo')

    # Test that we can serialize the assignment in a GET to the service-index endpoint
    service_url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(service_url + f'?user={rando.id}', format="json")
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1
    assignment_data = response.data['results'][0]
    assert assignment_data['object_id'] == str(assignment.object_id)

    # Direct serialization is used for synchronizing, so test that as well here
    serializer = ServiceRoleUserAssignmentSerializer(assignment)
    assignment_data = serializer.data
    assert assignment_data['object_id'] == str(assignment.object_id)


@pytest.mark.django_db
class TestRemoteObjectManagePermission:
    """Tests for check_content_obj_permission with RemoteObject and manage_action."""

    @pytest.fixture
    def change_foo_permission(self, foo_type):
        return DABPermission.objects.create(codename='change_foo', content_type=foo_type)

    @pytest.fixture
    def change_foo_rd(self, foo_type, change_foo_permission, foo_permission):
        return RoleDefinition.objects.create_from_permissions(
            name='Foo change+foo role',
            permissions=[change_foo_permission.api_slug, foo_permission.api_slug],
            content_type=foo_type,
        )

    @pytest.fixture
    def change_only_rd(self, foo_type, change_foo_permission):
        return RoleDefinition.objects.create_from_permissions(
            name='Foo change-only role',
            permissions=[change_foo_permission.api_slug],
            content_type=foo_type,
        )

    @pytest.fixture(autouse=True)
    def _make_users_visible(self, user, rando, org_admin_rd, org_member_rd, organization):
        org_admin_rd.give_permission(user, organization)
        org_member_rd.give_permission(rando, organization)

    def test_non_admin_with_change_can_assign_remote_role(self, user_api_client, user, rando, foo_type, foo_rd, change_foo_rd):
        a_foo = RemoteObject(content_type=foo_type, object_id=42)
        change_foo_rd.give_permission(user, a_foo)

        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={"role_definition": foo_rd.id, "user": rando.pk, "object_id": 42})
        assert response.status_code == 201, response.data

    def test_non_admin_without_change_cannot_assign_remote_role(self, user_api_client, user, rando, foo_type, foo_rd, change_foo_permission):
        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={"role_definition": foo_rd.id, "user": rando.pk, "object_id": 42})
        assert response.status_code == 403

    def test_escalation_blocked_for_remote_object(self, user_api_client, user, rando, foo_type, foo_rd, change_only_rd):
        a_foo = RemoteObject(content_type=foo_type, object_id=42)
        change_only_rd.give_permission(user, a_foo)

        url = get_relative_url('roleuserassignment-list')
        response = user_api_client.post(url, data={"role_definition": foo_rd.id, "user": rando.pk, "object_id": 42})
        assert response.status_code == 403
        assert 'foo_foo' in str(response.data)
