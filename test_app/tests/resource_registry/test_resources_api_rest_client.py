import uuid

import pytest
from requests.exceptions import HTTPError

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceAPIClient, ResourceRequestBody
from test_app.models import Inventory


@pytest.fixture
def resource_client(system_user, admin_user, live_server, local_authenticator, transactional_db) -> ResourceAPIClient:
    """
    Okay, there's a lot going on with this fixture, so let me explain.

    The `live_server` fixture is a weird one. The tests run in a separate thread from the
    django instance[1], so migration data doesn't exist. Because of that, we don't get
    the `_system user`, which comes from migrations[2], so that has to be created explicitly here
    because without the _system user, the system throws "ValueError: Unable to save model
    without user!" any time any model that inherits from CommonModel is saved. Theoretically
    the `django_db_serialized_rollback` should solve this problem, but when I added it
    everything completely breaks.

    The `transactional_db`[1] fixture is used to rollback tests when the django server is
    running in a different thread. It's slower than the `db`, but using the `db` fixture
    causes weird failures in other tests.

    [1] https://pytest-django.readthedocs.io/en/latest/helpers.html#live-server
    [2] test_app/migrations/0003_create_system_user.py
    """
    return ResourceAPIClient(live_server.url, "/api/v1/service-index/", jwt_user_id=admin_user.resource.ansible_id)


@pytest.fixture
def inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name='change-inv',
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )


@pytest.mark.django_db
def test_service_metadata(resource_client):
    """Test that the resource list is working."""
    resp = resource_client.get_service_metadata()

    assert resp.status_code == 200
    assert resp.json()["service_id"] == str(service_id())


@pytest.mark.django_db
def test_create_resource(resource_client):
    data = ResourceRequestBody(resource_type="shared.user", resource_data={"username": "mr_dab"})
    resp = resource_client.create_resource(data)

    assert resp.status_code == 201
    assert resp.json()["name"] == "mr_dab"

    new_service_id = str(uuid.uuid4())
    new_ansible_id = str(uuid.uuid4())

    data = ResourceRequestBody(
        ansible_id=new_ansible_id,
        service_id=new_service_id,
        resource_type="shared.user",
        resource_data={"username": "mrs_dab"},
    )
    resp = resource_client.create_resource(data)

    assert resp.status_code == 201
    assert resp.json()["name"] == "mrs_dab"
    assert resp.json()["ansible_id"] == new_ansible_id
    assert resp.json()["service_id"] == new_service_id
    assert resp.json()["is_partially_migrated"] is False


@pytest.mark.django_db
def test_get_resource(resource_client, organization):
    ansible_id = str(Resource.get_resource_for_object(organization).ansible_id)
    resp = resource_client.get_resource(ansible_id)

    assert resp.status_code == 200
    assert resp.json()["name"] == organization.name


@pytest.mark.django_db
def test_update_resource(resource_client, organization):
    ansible_id = str(Resource.get_resource_for_object(organization).ansible_id)
    data = ResourceRequestBody(resource_data={"name": "my_new_org"})
    resp = resource_client.update_resource(ansible_id, data)

    assert resp.status_code == 200
    assert resp.json()["name"] == "my_new_org"

    data = ResourceRequestBody(resource_data={"name": "my_new_org2"})
    resp = resource_client.update_resource(ansible_id, data, partial=True)

    assert resp.status_code == 200
    assert resp.json()["name"] == "my_new_org2"

    new_service_id = str(uuid.uuid4())
    new_ansible_id = str(uuid.uuid4())

    data = ResourceRequestBody(ansible_id=new_ansible_id, service_id=new_service_id)
    resp = resource_client.update_resource(ansible_id, data, partial=True)

    assert resp.status_code == 200
    assert resp.json()["name"] == "my_new_org2"
    assert resp.json()["ansible_id"] == new_ansible_id
    assert resp.json()["service_id"] == new_service_id

    data = ResourceRequestBody(is_partially_migrated=True)
    resp = resource_client.update_resource(new_ansible_id, data, partial=True)

    assert resp.status_code == 200
    assert resp.json()["is_partially_migrated"] is True


@pytest.mark.django_db
def test_delete_resource(resource_client, organization):
    ansible_id = str(Resource.get_resource_for_object(organization).ansible_id)
    resp = resource_client.delete_resource(ansible_id)

    assert resp.status_code == 204

    resp = resource_client.get_resource(ansible_id)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_resources(resource_client, organization):
    ansible_id = str(Resource.get_resource_for_object(organization).ansible_id)
    resp = resource_client.list_resources()
    assert resp.status_code == 200

    resp = resource_client.list_resources(filters={"ansible_id": ansible_id})

    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["results"][0]["ansible_id"] == ansible_id
    assert resp.json()["results"][0]["is_partially_migrated"] is False
    assert "additional_data" not in resp.json()["results"][0]


@pytest.mark.django_db
def test_bulk_update_resources(resource_client, organization):
    """Test bulk_update_resources client method."""
    resource = Resource.get_resource_for_object(organization)
    ansible_id = str(resource.ansible_id)
    new_service_id = str(uuid.uuid4())
    items = [{"ansible_id": ansible_id, "new_service_id": new_service_id}]

    resp = resource_client.bulk_update_resources(items)
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["errors"] == []

    resource.refresh_from_db()
    assert str(resource.service_id) == new_service_id


@pytest.mark.django_db
def test_get_resource_type(resource_client):
    resp = resource_client.get_resource_type("shared.organization")

    assert resp.status_code == 200
    assert resp.json()["name"] == "shared.organization"


@pytest.mark.django_db
def test_list_resource_types(resource_client):
    resp = resource_client.list_resource_types()
    assert resp.status_code == 200

    resp = resource_client.list_resource_types(filters={"name": "shared.organization"})

    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["results"][0]["name"] == "shared.organization"


@pytest.mark.django_db
def test_list_role_types(resource_client):
    resp = resource_client.list_role_types(filters={"api_slug": "shared.organization"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["results"][0]["api_slug"] == "shared.organization"


@pytest.mark.django_db
def test_list_role_permissions(resource_client):
    resp = resource_client.list_role_permissions(filters={"api_slug": "shared.view_organization"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["results"][0]["api_slug"] == "shared.view_organization"


@pytest.mark.django_db
def test_list_role_permissions_all_pages(resource_client):
    resp = resource_client.list_role_permissions()
    assert resp.status_code == 200
    assert resp.json()["next"] is not None
    assert resp.json()["count"] > 25


def _assert_assignment_matches_data(assignment, data, obj, actor):
    assert 'created' in data, data
    # assert DateTimeField().to_representation(assignment.created) == data['created']  # TODO
    assert str(assignment.created_by.resource.ansible_id) == data['created_by_ansible_id']
    assert assignment.object_id == obj.id
    assert str(assignment.object_id) == str(data['object_id'])
    if hasattr(obj, 'resource'):
        assert str(obj.resource.ansible_id) == data['object_ansible_id']
        assert 'shared.organization' == data['content_type']
        assert 'Organization Admin' == data['role_definition']
    else:
        assert 'aap.inventory' == data['content_type']
        assert 'change-inv' == data['role_definition']
    if 'user_ansible_id' in data:
        assert str(actor.resource.ansible_id) == data['user_ansible_id']
    elif 'team_ansible_id' in data:
        assert str(actor.resource.ansible_id) == data['team_ansible_id']


@pytest.mark.django_db
def test_sync_org_assignment(resource_client, org_admin_rd, user, organization):
    assignment = org_admin_rd.give_permission(user, organization)
    resp = resource_client.sync_assignment(assignment)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Existing assignment should be this current assignment
    _assert_assignment_matches_data(assignment, data, organization, user)

    org_admin_rd.remove_permission(user, organization)
    resp = resource_client.sync_assignment(assignment)  # assignment not actually here locally
    assert resp.status_code == 201, resp.text  # created
    data = resp.json()
    # All the data, on the remote system, should match our original assignment
    _assert_assignment_matches_data(assignment, data, organization, user)


@pytest.mark.django_db
def test_sync_obj_assignment(resource_client, user, inventory, inv_rd):
    assignment = inv_rd.give_permission(user, inventory)
    resp = resource_client.sync_assignment(assignment)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Existing assignment should be this current assignment
    _assert_assignment_matches_data(assignment, data, inventory, user)

    inv_rd.remove_permission(user, inventory)
    resp = resource_client.sync_assignment(assignment)  # assignment not actually here locally
    assert resp.status_code == 201, resp.text  # created
    data = resp.json()
    # All the data, on the remote system, should match our original assignment
    _assert_assignment_matches_data(assignment, data, inventory, user)


@pytest.mark.django_db
def test_get_resource_404(resource_client):
    resource_client.raise_if_bad_request = True

    with pytest.raises(HTTPError):
        resp = resource_client.get_resource(str(uuid.uuid4))
        assert resp.status_code == 404


@pytest.mark.django_db
def test_additional_data_read(resource_client, django_user_model, github_authenticator):
    user = django_user_model.objects.create(username="lisan_al_gaib")

    AuthenticatorUser.objects.create(provider=github_authenticator, user=user, uid="different_uid")

    ansible_id = str(Resource.get_resource_for_object(user).ansible_id)
    resp = resource_client.get_resource(ansible_id)

    assert resp.status_code == 200
    additional = resp.json()["additional_data"]

    assert "social_auth" in additional
    assert len(additional["social_auth"]) == 1
    assert additional["social_auth"][0]["uid"] == "different_uid"
    assert additional["social_auth"][0]["backend_type"] == github_authenticator.type
    assert additional["social_auth"][0]["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
@pytest.mark.parametrize('partial', [True, False])
def test_additional_data_write(resource_client, partial):
    "Will remove a permission from a role definition."
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['aap.change_inventory', 'aap.view_inventory'],
        name='change-inv-for-now',
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )
    ansible_id = str(rd.resource.ansible_id)

    # Need this to make a coherent PUT
    resp = resource_client.get_resource(ansible_id)
    assert resp.status_code == 200
    ref = resp.json()

    res_data = ref['resource_data']
    res_data['permissions'] = ['aap.view_inventory', 'fooland.action_unicorns']

    data = ResourceRequestBody(resource_data=res_data)
    resp = resource_client.update_resource(ansible_id, data, partial=partial)
    assert resp.status_code == 200, resp.__dict__

    # Removed the change permission
    assert {perm.api_slug for perm in rd.permissions.all()} == {'aap.view_inventory'}


@pytest.mark.django_db
def test_list_user_assignments(resource_client, org_admin_rd, user, organization):
    """Test listing user role assignments."""
    # Create an assignment for the user
    assignment = org_admin_rd.give_permission(user, organization)

    # Call the list_user_assignments method (doesn't exist yet)
    resp = resource_client.list_user_assignments(user_ansible_id=str(user.resource.ansible_id))

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1

    # Find our assignment in the results
    assignment_found = False
    for result in data["results"]:
        if result["user_ansible_id"] == str(user.resource.ansible_id):
            _assert_assignment_matches_data(assignment, result, organization, user)
            assignment_found = True
            break

    assert assignment_found, "User assignment not found in list results"


@pytest.mark.django_db
def test_list_team_assignments(resource_client, inv_rd, team, inventory):
    """Test listing team role assignments."""
    # Create an assignment for the team
    assignment = inv_rd.give_permission(team, inventory)

    # Call the list_team_assignments method (doesn't exist yet)
    resp = resource_client.list_team_assignments(team_ansible_id=str(team.resource.ansible_id))

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1

    # Find our assignment in the results
    assignment_found = False
    for result in data["results"]:
        if result["team_ansible_id"] == str(team.resource.ansible_id):
            _assert_assignment_matches_data(assignment, result, inventory, team)
            assignment_found = True
            break

    assert assignment_found, "Team assignment not found in list results"
