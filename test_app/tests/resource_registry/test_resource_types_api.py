import csv
from io import StringIO

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource


def test_resource_type_list(admin_api_client):
    """
    Test list api view for resource types
    """
    url = get_relative_url("resourcetype-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert set([x["name"] for x in response.data['results']]) == set(
        [
            "shared.user",
            "shared.team",
            "aap.authenticator",
            "aap.original1",
            "aap.original2",
            "shared.organization",
            "shared.roledefinition",
            "aap.resourcemigrationtestmodel",
            "shared.aapflag",
        ]
    )


def test_resource_type_detail(admin_api_client):
    """
    Test get api view for resource types
    """
    url = get_relative_url("resourcetype-detail", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "shared.user"


def test_resource_type_manifest(admin_api_client):
    """
    Test get the csv for resource type manifest
    """
    url = get_relative_url("resourcetype-manifest", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    response_data = list(response.streaming_content)
    data = StringIO("".join(item.decode() for item in response_data))
    for row in csv.DictReader(data):
        assert "ansible_id" in row
        assert "resource_hash" in row


def test_resource_type_manifest_404(admin_api_client):
    url = get_relative_url("resourcetype-manifest", kwargs={"name": "doesnt.exist"})
    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_resource_type_manifest_ordering(admin_api_client, django_user_model):
    """Manifest CSV rows must be ordered by Resource pk (ascending)."""
    for i in range(5):
        django_user_model.objects.create(username=f"ordtest_user{i}")

    url = get_relative_url("resourcetype-manifest", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200

    data = StringIO("".join(item.decode() for item in response.streaming_content))
    ansible_ids = [row["ansible_id"] for row in csv.DictReader(data)]

    resource_pks = list(Resource.objects.filter(ansible_id__in=ansible_ids).values_list("ansible_id", "id"))
    pk_by_ansible_id = {str(ansible_id): pk for ansible_id, pk in resource_pks}
    returned_pks = [pk_by_ansible_id[aid] for aid in ansible_ids]

    assert returned_pks == sorted(returned_pks)
