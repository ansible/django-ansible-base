from django.urls import reverse


def test_resource_type_list(admin_api_client):
    """
    Test list api view for resource types
    """
    url = reverse("resourcetype-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert set([x["name"] for x in response.data['results']]) == set(
        ["shared.user", "shared.team", "aap.authenticator", "shared.organization", "aap.resourcemigrationtestmodel"]
    )


def test_resource_type_detail(admin_api_client):
    """
    Test get api view for resource types
    """
    url = reverse("resourcetype-detail", kwargs={"name": "shared.user"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "shared.user"
