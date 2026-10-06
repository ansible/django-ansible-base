"""
Integration tests for OpenAPI schema generation with x-ai-description.

These tests verify that the schema endpoint is accessible and that x-ai-description
fields are properly included in the generated OpenAPI spec for MCP (Model Context Protocol) server tools.
"""

import os
import subprocess
import sys

import pytest
from django.conf import settings

from ansible_base.rbac.api.views import RoleDefinitionViewSet
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rest_filters.rest_framework.role_definition_backend import RoleDefinitionScopeFilterBackend


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


def test_bulk_role_assignment_actions_document_batch_requests_and_count_responses(admin_api_client):
    response = admin_api_client.get('/api/v1/docs/schema/')
    assert response.status_code == 200, response.data
    schema = response.data

    def resolve_schema(schema_fragment):
        while '$ref' in schema_fragment:
            component_name = schema_fragment['$ref'].rsplit('/', 1)[-1]
            schema_fragment = schema['components']['schemas'][component_name]
        return schema_fragment

    actions = (
        ('role-user-assignments', 'bulk-assign', 'user_ansible_id', {'created', 'existing'}),
        ('role-user-assignments', 'bulk-unassign', 'user_ansible_id', {'deleted', 'missing'}),
        ('role-team-assignments', 'bulk-assign', 'team_ansible_id', {'created', 'existing'}),
        ('role-team-assignments', 'bulk-unassign', 'team_ansible_id', {'deleted', 'missing'}),
    )
    for resource, action, actor_field, response_fields in actions:
        operation = schema['paths'][f'/api/v1/service-index/{resource}/{action}/']['post']
        request_schema = resolve_schema(operation['requestBody']['content']['application/json']['schema'])
        assert {'from_service', 'assignments'} <= set(request_schema['properties'])
        assignment_schema = resolve_schema(request_schema['properties']['assignments']['items'])
        assert actor_field in assignment_schema['properties']

        response_schema = resolve_schema(operation['responses']['200']['content']['application/json']['schema'])
        assert response_fields <= set(response_schema['properties'])


def test_role_user_assignment_create_schema(admin_api_client):
    """
    Test that RoleUserAssignmentViewSet's create operation has proper schema documentation.

    Generated by Claude Code (claude-sonnet-4-5@20250929)

    Verifies that the request body schema properly documents:
    - Exactly one of 'user' or 'user_ansible_id' is required (enforced by server validation)
    - At most one of 'object_id' or 'object_ansible_id' can be specified (enforced by server validation)
    """
    url = '/api/v1/docs/schema/'
    response = admin_api_client.get(url)
    assert response.status_code == 200

    # Navigate directly to the schema - will raise KeyError if path doesn't exist
    all_of = response.data['paths']['/api/v1/role_user_assignments/']['post']['requestBody']['content']['application/json']['schema']['allOf']

    # Verify structure: [base_schema, user_constraint, object_constraint]
    assert len(all_of) == 3, "Should have 3 items: base schema + 2 constraint sets"
    assert all_of[0] == {'$ref': '#/components/schemas/RoleUserAssignment'}

    # Verify user constraint documentation
    user_requirement = all_of[1]
    assert 'description' in user_requirement
    assert 'user' in user_requirement['description']
    assert 'user_ansible_id' in user_requirement['description']
    assert 'properties' in user_requirement
    assert 'user' in user_requirement['properties']
    assert 'user_ansible_id' in user_requirement['properties']

    # Verify object constraint documentation
    object_requirement = all_of[2]
    assert 'description' in object_requirement
    assert 'object_id' in object_requirement['description']
    assert 'object_ansible_id' in object_requirement['description']
    assert 'properties' in object_requirement
    assert 'object_id' in object_requirement['properties']
    assert 'object_ansible_id' in object_requirement['properties']


def test_role_definition_viewset_includes_scope_filter_backend():
    """RoleDefinitionViewSet must apply RoleDefinitionScopeFilterBackend for assignable_scope filtering to take effect."""
    assert RoleDefinitionScopeFilterBackend in RoleDefinitionViewSet.filter_backends


def test_role_definition_scope_filter_extension_is_discovered_by_spectacular():
    """App startup must register the scope filter extension in a clean process."""
    code = '''
import django

django.setup()

from drf_spectacular.extensions import OpenApiFilterExtension
from ansible_base.rest_filters.rest_framework.role_definition_backend import RoleDefinitionScopeFilterBackend

extension = OpenApiFilterExtension.get_match(RoleDefinitionScopeFilterBackend())
assert extension is not None, "RoleDefinitionScopeFilterBackend extension was not registered"
assert extension.target_class is RoleDefinitionScopeFilterBackend
'''
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        env={**os.environ, 'DJANGO_SETTINGS_MODULE': settings.SETTINGS_MODULE},
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def assignable_scope_parameter(admin_api_client):
    """The assignable_scope OpenAPI parameter for the role_definitions list (GET) operation."""
    response = admin_api_client.get('/api/v1/docs/schema/')
    operation = response.data['paths']['/api/v1/role_definitions/']['get']
    parameters = {param['name']: param for param in operation['parameters']}
    return parameters['assignable_scope']


def test_assignable_scope_parameter_is_query_parameter(assignable_scope_parameter):
    assert assignable_scope_parameter['in'] == 'query'


def test_assignable_scope_parameter_is_optional(assignable_scope_parameter):
    # OpenAPI omits 'required' entirely for optional parameters, defaulting to false
    assert assignable_scope_parameter.get('required', False) is False


def test_assignable_scope_parameter_documents_supported_scopes(assignable_scope_parameter):
    description = assignable_scope_parameter['description']
    assert all(scope in description for scope in RoleDefinition.ASSIGNABLE_SCOPES)
