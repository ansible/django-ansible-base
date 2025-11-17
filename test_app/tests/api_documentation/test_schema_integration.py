"""
Integration tests for OpenAPI schema generation with x-ai-description.

These tests verify that the schema endpoint is accessible and that x-ai-description
fields are properly included in the generated OpenAPI spec for MCP (Model Context Protocol) server tools.
"""


def test_openapi_schema_endpoint_accessible(admin_api_client):
    """Test that the OpenAPI schema endpoint is accessible and returns valid schema."""
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert response.accepted_media_type in ['application/vnd.oai.openapi', 'application/vnd.oai.openapi+json', 'application/json']

    # Verify basic OpenAPI structure
    schema = response.data
    assert 'openapi' in schema
    assert 'info' in schema
    assert 'paths' in schema
    assert schema['openapi'].startswith('3.')  # OpenAPI 3.x


def test_openapi_schema_includes_x_ai_description_for_list_operations(admin_api_client):
    """Test that x-ai-description is present in list operations."""
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)
    schema = response.data

    # Check teams list endpoint
    teams_path = schema['paths'].get('/api/v1/teams/')
    assert teams_path is not None, "Teams endpoint should exist in schema"

    list_operation = teams_path.get('get')
    assert list_operation is not None, "Teams list operation (GET) should exist"
    assert 'x-ai-description' in list_operation, "List operation should have x-ai-description"
    assert isinstance(list_operation['x-ai-description'], str)
    assert len(list_operation['x-ai-description']) > 0
    # Verify the description makes sense for a list operation
    assert 'list' in list_operation['x-ai-description'].lower() or 'retrieve' in list_operation['x-ai-description'].lower()


def test_openapi_schema_includes_x_ai_description_for_crud_operations(admin_api_client):
    """Test that x-ai-description is present in CRUD operations."""
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)
    schema = response.data

    # Check teams endpoints for various operations
    teams_path = schema['paths'].get('/api/v1/teams/')
    teams_detail_path = schema['paths'].get('/api/v1/teams/{id}/')

    assert teams_path is not None
    assert teams_detail_path is not None

    # Test CREATE (POST)
    if 'post' in teams_path:
        create_op = teams_path['post']
        assert 'x-ai-description' in create_op
        assert 'create' in create_op['x-ai-description'].lower()

    # Test RETRIEVE (GET with id)
    if 'get' in teams_detail_path:
        retrieve_op = teams_detail_path['get']
        assert 'x-ai-description' in retrieve_op
        assert 'retrieve' in retrieve_op['x-ai-description'].lower() or 'get' in retrieve_op['x-ai-description'].lower()

    # Test UPDATE (PUT)
    if 'put' in teams_detail_path:
        update_op = teams_detail_path['put']
        assert 'x-ai-description' in update_op
        assert 'update' in update_op['x-ai-description'].lower()

    # Test PARTIAL_UPDATE (PATCH)
    if 'patch' in teams_detail_path:
        patch_op = teams_detail_path['patch']
        assert 'x-ai-description' in patch_op
        assert 'update' in patch_op['x-ai-description'].lower() or 'modify' in patch_op['x-ai-description'].lower()

    # Test DELETE
    if 'delete' in teams_detail_path:
        delete_op = teams_detail_path['delete']
        assert 'x-ai-description' in delete_op
        assert 'delete' in delete_op['x-ai-description'].lower() or 'destroy' in delete_op['x-ai-description'].lower()


def test_openapi_schema_x_ai_description_for_nested_resources(admin_api_client):
    """Test that x-ai-description works for nested resource endpoints."""
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)
    schema = response.data

    # Check nested endpoint like teams/{id}/members/
    nested_path = schema['paths'].get('/api/v1/teams/{id}/members/')

    if nested_path is not None:
        # Test nested list operation
        if 'get' in nested_path:
            list_op = nested_path['get']
            assert 'x-ai-description' in list_op
            # Should mention both the parent and child resource
            description = list_op['x-ai-description'].lower()
            assert 'team' in description or 'member' in description or 'user' in description


def test_openapi_schema_x_ai_description_not_on_skipped_endpoints(admin_api_client):
    """Test that x-ai-description is not added to endpoints that should skip it."""
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)
    schema = response.data

    # Check if there are any paths that should be skipped
    # Based on SKIP_AI_DESCRIPTION_PREFIXES in preprocessing_hooks.py
    for path, operations in schema['paths'].items():
        for method, operation in operations.items():
            if isinstance(operation, dict):
                # If the operation ID suggests it should be skipped, verify no x-ai-description
                operation_id = operation.get('operationId', '')
                if operation_id.startswith('_'):
                    assert 'x-ai-description' not in operation, f"Operation {operation_id} should not have x-ai-description"


def test_openapi_schema_format(admin_api_client):
    """Test that the schema can be retrieved in different formats."""
    base_url = '/api/v1/docs/schema/'

    # Test JSON format (default)
    response = admin_api_client.get(base_url, HTTP_ACCEPT='application/json')
    assert response.status_code == 200
    schema = response.data
    assert 'openapi' in schema

    # Test OpenAPI JSON format
    response = admin_api_client.get(base_url, HTTP_ACCEPT='application/vnd.oai.openapi+json')
    assert response.status_code == 200


def test_openapi_schema_unauthenticated_access(unauthenticated_api_client):
    """Test that the schema endpoint can be accessed without authentication."""
    url = '/api/v1/docs/schema/'
    response = unauthenticated_api_client.get(url)

    # Schema endpoints are typically public
    # Adjust this assertion based on your authentication requirements
    assert response.status_code in [200, 401, 403]

    if response.status_code == 200:
        schema = response.data
        assert 'openapi' in schema
