from django.urls import reverse

from ansible_base.resource_registry.models import service_id


def test_service_metadata(admin_api_client):
    """Test that the resource list is working."""
    url = reverse("service-metadata")
    resp = admin_api_client.get(url)

    assert resp.status_code == 200
    assert resp.data["service_type"] == "aap"
    assert resp.data["service_id"] == service_id()
