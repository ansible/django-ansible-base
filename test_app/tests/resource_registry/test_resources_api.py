import uuid

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.resource_registry.models import Resource
from test_app.models import EncryptionModel, Organization, Team


def test_resources_list(admin_api_client):
    """Test that the resource list is working."""
    url = reverse("resource-list")
    resp = admin_api_client.get(url + "?content_type__resource_type__name=aap.resourcemigrationtestmodel")

    assert resp.status_code == 200
    assert resp.data['count'] == 1
    assert resp.data['results'][0]["name"] == "migration resource"
    assert resp.data['results'][0]["resource_type"] == "aap.resourcemigrationtestmodel"


def test_resource_list_all_types(organization, user, team, admin_api_client):
    resp = admin_api_client.get(reverse("resource-list"))
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
    admin_api_client.delete(reverse("resource-detail", kwargs={"ansible_id": ansible_id}))

    assert not Resource.objects.filter(object_id=user.pk, content_type=c_type.pk).exists()
    assert not django_user_model.objects.filter(pk=user.pk).exists()


def test_resources_api_invalid_delete(admin_api_client):
    """Test that resources can be correctly deleted via the API."""

    # Since groups are not set to be managed externally, we can't delete them with this API
    org = Organization.objects.create(name="my org")
    group = Team.objects.create(name="super group", organization=org)
    c_type = ContentType.objects.get_for_model(group)
    assert Resource.objects.filter(object_id=group.pk, content_type=c_type.pk).exists()

    ansible_id = Resource.objects.get(object_id=group.pk, content_type=c_type.pk).ansible_id
    resp = admin_api_client.delete(reverse("resource-detail", kwargs={"ansible_id": ansible_id}))

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

    url = reverse("resource-detail", kwargs={"ansible_id": resource.ansible_id})

    data = {"resource_type": "shared.user", "resource_data": {"username": user.username}}

    data["resource_data"]["username"] = "new_username"
    admin_api_client.put(url, data, format="json")

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
    new_ansible_id = "12345678" + ":" + str(uuid.uuid4())

    url = reverse("resource-detail", kwargs={"ansible_id": ansible_id})

    data = {"ansible_id": new_ansible_id}
    resp = admin_api_client.patch(url, data, format="json")
    assert resp.status_code == 200
    assert resp.data["ansible_id"] == new_ansible_id

    assert admin_api_client.get(url).status_code == 404

    resp = admin_api_client.get(reverse("resource-detail", kwargs={"ansible_id": new_ansible_id}))

    assert resp.status_code == 200
    assert resp.data["ansible_id"] == new_ansible_id


def test_resource_partial_update(admin_api_client, user):
    """Test that partial update works correctly."""
    c_type = ContentType.objects.get_for_model(user)
    ansible_id = Resource.objects.get(object_id=user.pk, content_type=c_type.pk).ansible_id

    url = reverse("resource-detail", kwargs={"ansible_id": ansible_id})

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
        {"ansible_id": "0433e6b7:a0057c59-776d-48f8-97f1-8f8033e68d93", "resource_type": "shared.organization", "resource_data": {"name": "foo"}},
        {"resource_type": "shared.organization", "resource_data": {"name": "my super cool org"}},
        {"ansible_id": "0433e6b7:a0057c59-776d-48f8-97f1-8f8033e68d93", "resource_type": "shared.user", "resource_data": {"username": "foo"}},
        {
            "ansible_id": "0433e6b7:a0057c59-776d-48f8-97f1-8f8033e68d93",
            "resource_type": "shared.user",
            "resource_data": {"username": "MrFoo", "first_name": "Mr", "last_name": "Foo", "email": "mrfoo@redhat.com", "is_superuser": True},
        },
        {
            "resource_type": "shared.user",
            "resource_data": {"username": "Bobby", "last_name": "Bobberton", "email": "bobby@redhat.com", "is_superuser": False},
        },
    ],
)
def test_resources_api_crd(admin_api_client, resource):
    """Test create, read, delete."""
    # create resource
    url = reverse("resource-list")
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    if "ansible_id" in resource:
        assert response.data["ansible_id"] == resource["ansible_id"]

    assert response.data["resource_type"] == resource["resource_type"]

    for key in resource["resource_data"]:
        assert response.data["resource_data"][key] == resource["resource_data"][key]

    # read resource
    detail_url = reverse("resource-detail", kwargs={"ansible_id": response.data["ansible_id"]})
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
            "data": {"ansible_id": "a0057c59-776d-48f8-97f1-8f8033e68d91", "resource_type": "shared.team", "resource_data": {"name": "foo"}},
            "field_name": "ansible_id",
        },
        {"data": {"ansible_id": "0433e6b7:null", "resource_type": "shared.team", "resource_data": {"name": "foo"}}, "field_name": "ansible_id"},
        {
            "data": {"ansible_id": "123:a0057c59-776d-48f8-97f1-8f8033e68d91", "resource_type": "shared.team", "resource_data": {"name": "foo"}},
            "field_name": "ansible_id",
        },
        {
            "data": {"ansible_id": "????????:a0057c59-776d-48f8-97f1-8f8033e68d91", "resource_type": "shared.team", "resource_data": {"name": "foo"}},
            "field_name": "ansible_id",
        },
        {"data": {"resource_type": "shared.team", "resource_data": {"name": "foo"}}, "field_name": "resource_type"},
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
    url = reverse("resource-list")
    response = admin_api_client.post(url, resource["data"], format="json")
    assert response.status_code == 400
    assert resource["field_name"] in response.data
