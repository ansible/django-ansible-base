import uuid

import pytest
from requests.exceptions import HTTPError

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceAPIClient, ResourceRequestBody


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
def test_get_resource_404(resource_client):
    resource_client.raise_if_bad_request = True

    with pytest.raises(HTTPError):
        resp = resource_client.get_resource(str(uuid.uuid4))
        assert resp.status_code == 404


@pytest.mark.django_db
def test_additional_data(resource_client, django_user_model, github_authenticator):
    user = django_user_model.objects.create(username="lisan_al_gaib")

    AuthenticatorUser.objects.create(provider=github_authenticator, user=user, uid="different_uid")

    ansible_id = str(Resource.get_resource_for_object(user).ansible_id)
    resp = resource_client.get_resource(ansible_id)

    assert resp.status_code == 200
    additional = resp.json()["additional_data"]

    assert "social_auth" in additional
    assert len(additional["social_auth"]) == 1
    assert additional["social_auth"][0]["social_uid"] == "different_uid"
    assert additional["social_auth"][0]["social_backend"] == github_authenticator.type


@pytest.mark.django_db
def test_validate_local_user(resource_client, admin_user, member_rd):
    resp = resource_client.validate_local_user(username=admin_user.username, password="password")

    assert resp.status_code == 200
    assert resp.json()["ansible_id"] == str(admin_user.resource.ansible_id)

    resp = resource_client.validate_local_user(username=admin_user.username, password="fake password")

    assert resp.status_code == 401
