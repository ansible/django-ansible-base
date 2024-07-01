from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id


def test_service_metadata(admin_api_client):
    """Test that the resource list is working."""
    url = get_relative_url("service-metadata")
    resp = admin_api_client.get(url)

    assert resp.status_code == 200
    assert resp.data["service_type"] == "aap"
    assert resp.data["service_id"] == service_id()
