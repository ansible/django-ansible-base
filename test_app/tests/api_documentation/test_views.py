"""
Tests for API documentation views.
"""


def test_docs_root_view_returns_index(unauthenticated_api_client):
    """Test that the docs root endpoint returns an index of documentation endpoints."""
    url = '/api/v1/docs/'
    response = unauthenticated_api_client.get(url)

    assert response.status_code == 200
    data = response.data

    # Verify all expected keys are present
    assert 'swagger' in data
    assert 'redoc' in data
    assert 'schema' in data

    # Verify URLs point to the correct endpoints
    assert '/docs/swagger/' in data['swagger']
    assert '/docs/redoc/' in data['redoc']
    assert '/docs/schema/' in data['schema']


def test_docs_root_view_allows_unauthenticated_access(unauthenticated_api_client):
    """Test that the docs root endpoint is accessible without authentication."""
    url = '/api/v1/docs/'
    response = unauthenticated_api_client.get(url)

    assert response.status_code == 200


def test_swagger_ui_accessible(unauthenticated_api_client):
    """Test that Swagger UI is accessible at the new URL."""
    url = '/api/v1/docs/swagger/'
    response = unauthenticated_api_client.get(url)

    assert response.status_code == 200


def test_redoc_accessible(unauthenticated_api_client):
    """Test that ReDoc is accessible."""
    url = '/api/v1/docs/redoc/'
    response = unauthenticated_api_client.get(url)

    assert response.status_code == 200
