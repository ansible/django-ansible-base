from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id


def test_service_metadata(admin_api_client):
    """Test that the resource list is working."""
    url = get_relative_url("service-metadata")
    resp = admin_api_client.get(url)

    assert resp.status_code == 200
    assert resp.data["service_type"] == "aap"
    assert resp.data["service_id"] == service_id()


def test_service_metadata_schema(admin_api_client):
    response = admin_api_client.get('/api/v1/docs/schema/')
    assert response.status_code == 200
    openapi_schema = response.data
    operation = openapi_schema['paths'][get_relative_url('service-metadata')]['get']
    assert operation['operationId'] == 'service_index_metadata_retrieve'
    response_schema = operation['responses']['200']['content']['application/json']['schema']

    assert response_schema == {'$ref': '#/components/schemas/ServiceIndexMetadata'}
    metadata_schema = openapi_schema['components']['schemas']['ServiceIndexMetadata']
    assert metadata_schema['properties'] == {
        'service_id': {'type': 'string', 'format': 'uuid'},
        'service_type': {'type': 'string'},
    }
    assert set(metadata_schema['required']) == {'service_id', 'service_type'}
