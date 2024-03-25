import csv
from io import StringIO

from django.urls import reverse


def test_resource_type_list(admin_api_client):
    """
    Test list api view for resource types
    """
    url = reverse("resourcetype-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert set([x["name"] for x in response.data['results']]) == set(
        ["shared.user", "shared.team", "aap.authenticator", "aap.original1", "aap.original2", "shared.organization", "aap.resourcemigrationtestmodel"]
    )


def test_resource_type_detail(admin_api_client):
    """
    Test get api view for resource types
    """
    url = reverse("resourcetype-detail", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "shared.user"


def test_resource_type_manifest(admin_api_client):
    """
    Test get the csv for resource type manifest
    """
    url = reverse("resourcetype-manifest", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    response_data = list(response.streaming_content)
    data = StringIO("".join(item.decode() for item in response_data))
    for row in csv.DictReader(data):
        assert "ansible_id" in row
        assert "resource_hash" in row


def test_resource_type_manifest_404(admin_api_client):
    url = reverse("resourcetype-manifest", kwargs={"name": "doesnt.exist"})
    response = admin_api_client.get(url)
    assert response.status_code == 404
