import csv
from io import StringIO

from ansible_base.lib.utils.response import get_relative_url


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
    rows = list(csv.DictReader(data))
    for row in rows:
        assert "ansible_id" in row
        assert "resource_hash" in row
    # The X-Resource-Count header must reflect exactly how many data rows were streamed,
    # so clients can detect a truncated/incomplete transfer.
    assert response.headers["X-Resource-Count"] == str(len(rows))


def test_resource_type_manifest_404(admin_api_client):
    url = get_relative_url("resourcetype-manifest", kwargs={"name": "doesnt.exist"})
    response = admin_api_client.get(url)
    assert response.status_code == 404
    # A 404 has no resources to count — it must not claim a (misleading) count of 0.
    assert "X-Resource-Count" not in response.headers
