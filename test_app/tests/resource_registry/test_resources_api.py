import uuid
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor
from test_app.models import EncryptionModel, Organization
from test_app.resource_api import APIConfig


def test_service_index_root(user_api_client):
    resp = user_api_client.get(get_relative_url('service-index-root'))
    assert resp.status_code == 200
    assert 'metadata' in resp.data
    assert 'resources' in resp.data
    assert 'resource-types' in resp.data


def test_resources_list(admin_api_client):
    """Test that the resource list is working."""
    url = get_relative_url("resource-list")
    resp = admin_api_client.get(url + "?content_type__resource_type__name=aap.resourcemigrationtestmodel")

    assert resp.status_code == 200
    assert resp.data['count'] == 1
    assert resp.data['results'][0]["name"] == "migration resource"
    assert resp.data['results'][0]["resource_type"] == "aap.resourcemigrationtestmodel"


def test_resource_list_all_types(organization, user, team, admin_api_client):
    resp = admin_api_client.get(get_relative_url("resource-list"))
    assert resp.status_code == 200, resp.data

    # lazy way of checking that objects are in the output
    for obj in (organization, team):
        assert obj.name in str(resp.data)
    assert user.username in str(resp.data)


def test_resources_delete(django_user_model):
    """Test that the Resource object gets cleaned up when a model instance is deleted."""
    user = django_user_model.objects.create(username="foo")
    assert Resource.objects.filter(name=user.username, object_id=user.pk, content_type=ContentType.objects.get_for_model(user).pk).exists()

    user.delete()

    assert not Resource.objects.filter(name=user.username, object_id=user.pk, content_type=ContentType.objects.get_for_model(user).pk).exists()


def test_resources_delete_api(admin_api_client, django_user_model):
    """Test that resources can be correctly deleted via the API."""
    user = django_user_model.objects.create(username="foo")
    c_type = ContentType.objects.get_for_model(user)

    assert Resource.objects.filter(name=user.username, object_id=user.pk, content_type=c_type.pk).exists()

    ansible_id = Resource.objects.get(object_id=user.pk, content_type=c_type.pk).ansible_id
    admin_api_client.delete(get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id}))

    assert not Resource.objects.filter(object_id=user.pk, content_type=c_type.pk).exists()
    assert not django_user_model.objects.filter(pk=user.pk).exists()


def test_resources_api_invalid_delete(admin_api_client, local_authenticator):
    """Test that resources can be correctly deleted via the API."""

    # Authenticator is not allowed to be managed by the resources api
    ansible_id = Resource.get_resource_for_object(local_authenticator).ansible_id
    resp = admin_api_client.delete(get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id}))

    assert resp.status_code == 400
    assert "resource_type" in resp.data


@pytest.mark.django_db
def test_non_resources_arent_created():
    obj = EncryptionModel.objects.create()
    assert not Resource.objects.filter(object_id=obj.pk, content_type=ContentType.objects.get_for_model(obj)).exists()


def test_resource_update(
    admin_api_client,
    user,
):
    """Test that a resource can be updated via the API or django model."""
    c_type = ContentType.objects.get_for_model(user)
    resource = Resource.objects.get(object_id=user.pk, content_type=c_type.pk)

    url = get_relative_url("resource-detail", kwargs={"ansible_id": resource.ansible_id})

    data = {"resource_type": "shared.user", "resource_data": {"username": user.username}}

    data["resource_data"]["username"] = "new_username"
    resp = admin_api_client.put(url, data, format="json")
    assert resp.status_code == 200

    data = admin_api_client.get(url).data

    assert data["resource_data"]["username"] == "new_username"
    assert data["name"] == "new_username"

    user.username = "new_username_2"
    user.save()

    data = admin_api_client.get(url).data

    assert data["resource_data"]["username"] == "new_username_2"
    assert data["name"] == "new_username_2"


def test_resource_update_ansible_id(admin_api_client, user):
    """Test that the ansible ID of a resource can be updated."""
    c_type = ContentType.objects.get_for_model(user)
    ansible_id = Resource.objects.get(object_id=user.pk, content_type=c_type.pk).ansible_id
    new_ansible_id = str(uuid.uuid4())

    url = get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id})

    data = {"ansible_id": new_ansible_id}
    resp = admin_api_client.patch(url, data, format="json")
    assert resp.status_code == 200
    assert resp.data["ansible_id"] == new_ansible_id

    assert admin_api_client.get(url).status_code == 404

    resp = admin_api_client.get(get_relative_url("resource-detail", kwargs={"ansible_id": new_ansible_id}))

    assert resp.status_code == 200
    assert resp.data["ansible_id"] == new_ansible_id


def test_resource_update_service_id(admin_api_client, user):
    """Test that the service ID of a resource can be updated."""
    c_type = ContentType.objects.get_for_model(user)
    ansible_id = Resource.objects.get(object_id=user.pk, content_type=c_type.pk).ansible_id
    new_service_id = str(uuid.uuid4())

    url = get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id})

    data = {"service_id": new_service_id}
    resp = admin_api_client.patch(url, data, format="json")
    assert resp.status_code == 200
    assert resp.data["service_id"] == new_service_id


def test_resource_partial_update(admin_api_client, user):
    """Test that partial update works correctly."""
    c_type = ContentType.objects.get_for_model(user)
    ansible_id = Resource.objects.get(object_id=user.pk, content_type=c_type.pk).ansible_id

    url = get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id})

    resp = admin_api_client.patch(url, {"resource_data": {"first_name": "foo", "is_superuser": True}}, format="json")
    assert resp.status_code == 200

    resource_data = resp.data["resource_data"]

    assert resource_data["username"] == user.username
    assert resource_data["first_name"] == "foo"
    assert resource_data["last_name"] == ""
    assert resource_data["is_superuser"] is True

    resp = admin_api_client.patch(url, {"resource_data": {"last_name": "bar"}}, format="json")
    assert resp.status_code == 200

    resource_data = resp.data["resource_data"]
    assert resource_data["username"] == user.username
    assert resource_data["first_name"] == "foo"
    assert resource_data["last_name"] == "bar"
    assert resource_data["is_superuser"] is True


@pytest.mark.parametrize(
    'resource',
    [
        {"ansible_id": "a0057c59-776d-48f8-97f1-8f8033e68d93", "resource_type": "shared.organization", "resource_data": {"name": "foo"}},
        {"resource_type": "shared.organization", "resource_data": {"name": "my super cool org"}},
        {"ansible_id": "a0057c59-776d-48f8-97f1-8f8033e68d93", "resource_type": "shared.user", "resource_data": {"username": "foo"}},
        {
            "ansible_id": "a0057c59-776d-48f8-97f1-8f8033e68d93",
            "service_id": "ae417fc0-885c-49cb-b052-62cfc8e178b4",
            "resource_type": "shared.user",
            "resource_data": {"username": "MrFoo", "first_name": "Mr", "last_name": "Foo", "email": "mrfoo@redhat.com", "is_superuser": True},
        },
        {
            "resource_type": "shared.user",
            "resource_data": {"username": "Bobby", "last_name": "Bobberton", "email": "bobby@redhat.com", "is_superuser": False},
        },
        {
            "service_id": "79f8c69e-a974-4bab-8e0f-e9d4bd4efe81",
            "resource_type": "shared.user",
            "resource_data": {"username": "Bobby", "last_name": "Bobberton", "email": "bobby@redhat.com", "is_superuser": False},
        },
    ],
)
def test_resources_api_crd(admin_api_client, resource):
    """Test create, read, delete."""
    # create resource
    url = get_relative_url("resource-list")
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    if "ansible_id" in resource:
        assert response.data["ansible_id"] == resource["ansible_id"]

    if "service_id" in resource:
        assert response.data["service_id"] == resource["service_id"]

    assert response.data["resource_type"] == resource["resource_type"]

    for key in resource["resource_data"]:
        assert response.data["resource_data"][key] == resource["resource_data"][key]

    # read resource
    detail_url = get_relative_url("resource-detail", kwargs={"ansible_id": response.data["ansible_id"]})
    detail_response = admin_api_client.get(detail_url)
    assert detail_response.status_code == 200
    assert detail_response.data["ansible_id"] == response.data["ansible_id"]

    # delete resource
    delete_response = admin_api_client.delete(detail_url)
    assert delete_response.status_code == 204

    detail_response = admin_api_client.get(detail_url)
    assert detail_response.status_code == 404


@pytest.mark.parametrize(
    'resource',
    [
        {"data": {"ansible_id": "bogus", "resource_type": "shared.user", "resource_data": {"name": "foo"}}, "field_name": "ansible_id"},
        {
            "data": {
                "ansible_id": "a0057c59-776d-48f8-97f1-8f8033e68d91",
                "service_id": "bogus",
                "resource_type": "shared.user",
                "resource_data": {"name": "foo"},
            },
            "field_name": "service_id",
        },
        {
            "data": {
                "ansible_id": "bogus",
                "service_id": "a0057c59-776d-48f8-97f1-8f8033e68d91",
                "resource_type": "shared.user",
                "resource_data": {"name": "foo"},
            },
            "field_name": "ansible_id",
        },
        {"data": {"ansible_id": "null", "resource_type": "shared.team", "resource_data": {"name": "foo"}}, "field_name": "ansible_id"},
        {
            "data": {"ansible_id": "123-a0057c59-776d-48f8-97f1-8f8033e68d91", "resource_type": "shared.team", "resource_data": {"name": "foo"}},
            "field_name": "ansible_id",
        },
        {
            "data": {"ansible_id": "a0057c59033e68d91", "resource_type": "shared.team", "resource_data": {"name": "foo"}},
            "field_name": "ansible_id",
        },
        {"data": {"resource_type": "shared.user", "resource_data": {}}, "field_name": "username"},
        {"data": {"resource_type": "aap.authenticator", "resource_data": {}}, "field_name": "resource_type"},
        {"data": {"resource_type": "fake.fake", "resource_data": {}}, "field_name": "resource_type"},
        {"data": {"resource_type": "shared.user", "resource_data": {"last_name": "stark"}}, "field_name": "username"},
        {"data": {"resource_type": "shared.user", "resource_data": {"username": "bad_email", "email": "null"}}, "field_name": "email"},
        {"data": {"resource_type": "shared.organization", "resource_data": {}}, "field_name": "name"},
    ],
)
def test_resources_create_invalid(admin_api_client, resource):
    """Test validation on resource API for resource creation."""
    # create resource
    url = get_relative_url("resource-list")
    response = admin_api_client.post(url, resource["data"], format="json")
    assert response.status_code == 400
    assert resource["field_name"] in response.data


def test_resource_summary_fields(
    admin_api_client,
    organization,
):
    resource = Resource.get_resource_for_object(organization)

    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})

    resp = admin_api_client.get(url)
    assert resp.status_code == 200

    data = resp.data

    assert "resource" in data["summary_fields"]
    assert data["summary_fields"]["resource"]["ansible_id"] == resource.ansible_id
    assert data["summary_fields"]["resource"]["resource_type"] == "shared.organization"


def test_team_organization_field(admin_api_client, organization, organization_1, team):
    team_id = str(team.resource.ansible_id)
    org0_id = str(organization.resource.ansible_id)
    org1_id = str(organization_1.resource.ansible_id)

    url = get_relative_url("resource-detail", kwargs={"ansible_id": team_id})

    # Test that organization field exists
    resp = admin_api_client.get(url)
    assert resp.status_code == 200
    assert resp.data["resource_data"]["organization"] == org0_id

    # Test updating the organization field
    data = {"resource_data": {"organization": org1_id}}
    resp = admin_api_client.patch(url, data, format="json")
    assert resp.status_code == 200
    assert resp.data["resource_data"]["organization"] == org1_id

    team.refresh_from_db()
    assert team.organization == organization_1


def test_team_organization_field_does_not_exist(admin_api_client, team):
    # Test invalid organization ID
    bad_id = str(uuid.uuid4())
    team_id = str(team.resource.ansible_id)

    url = get_relative_url("resource-detail", kwargs={"ansible_id": team_id})

    data = {"resource_data": {"organization": bad_id}}
    resp = admin_api_client.patch(url, data, format="json")
    assert resp.status_code == 400
    assert bad_id in resp.data["organization"][0]


def test_processor_pre_serialize(admin_api_client, organization):
    class CustomProcessor(ResourceTypeProcessor):
        def pre_serialize(self):
            self.instance.name = "PRE SERIALIZED"
            return self.instance

    class PatchedConfig(APIConfig):
        custom_resource_processors = {"shared.organization": CustomProcessor}

    url = get_relative_url("resource-detail", kwargs={"ansible_id": str(organization.resource.ansible_id)})

    with patch("test_app.resource_api.APIConfig", PatchedConfig):
        resp = admin_api_client.get(url)
        assert resp.data["resource_data"]["name"] == "PRE SERIALIZED"


def test_processor_save(admin_api_client):
    class CustomProcessor(ResourceTypeProcessor):
        def save(self, validated_data, is_new=False):
            self.instance.name = "HELLO " + validated_data["name"]
            self.instance.save()
            return self.instance

    class PatchedConfig(APIConfig):
        custom_resource_processors = {"shared.organization": CustomProcessor}

    with patch("test_app.resource_api.APIConfig", PatchedConfig):
        # Test creating an organization
        url = get_relative_url("resource-list")
        resp = admin_api_client.post(url, {"resource_type": "shared.organization", "resource_data": {"name": "my_name"}}, format="json")
        assert resp.data["name"] == "HELLO my_name"
        assert Organization.objects.filter(name="HELLO my_name").exists()

        # Test updating an organization
        url = get_relative_url("resource-detail", kwargs={"ansible_id": resp.data["ansible_id"]})
        resp = admin_api_client.put(url, {"resource_data": {"name": "my_name2"}}, format="json")
        assert resp.data["name"] == "HELLO my_name2"
        assert Organization.objects.filter(name="HELLO my_name2").exists()
