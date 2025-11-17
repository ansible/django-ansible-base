"""
Unit tests for api_path_utils module.

These tests verify the utility functions used for parsing API paths and operation IDs
in both preprocessing and postprocessing hooks.
"""

from ansible_base.lib.utils.api_path_utils import (
    extract_operation_action,
    extract_operation_prefix,
    filter_api_prefixes,
    parse_path_segments,
)


class TestParsePathSegments:
    """Test the parse_path_segments function."""

    def test_simple_path(self):
        """Test parsing a simple API path."""
        result = parse_path_segments('/api/v1/teams/')
        assert result == ['api', 'v1', 'teams']

    def test_path_with_django_placeholder(self):
        """Test that Django-style placeholders (<pk>) are excluded."""
        result = parse_path_segments('/api/v1/teams/<pk>/')
        assert result == ['api', 'v1', 'teams']

    def test_path_with_openapi_placeholder(self):
        """Test that OpenAPI-style placeholders ({id}) are excluded."""
        result = parse_path_segments('/api/v1/teams/{id}/')
        assert result == ['api', 'v1', 'teams']

    def test_nested_path_with_placeholders(self):
        """Test parsing nested path with multiple placeholders."""
        result = parse_path_segments('/api/v1/teams/{id}/users/{pk}/')
        assert result == ['api', 'v1', 'teams', 'users']

    def test_path_with_multiple_placeholder_types(self):
        """Test path with both Django and OpenAPI placeholders."""
        result = parse_path_segments('/api/v1/teams/<pk>/users/{id}/')
        assert result == ['api', 'v1', 'teams', 'users']

    def test_empty_path(self):
        """Test parsing empty path."""
        result = parse_path_segments('')
        assert result == []

    def test_root_path(self):
        """Test parsing root path."""
        result = parse_path_segments('/')
        assert result == []

    def test_path_without_leading_slash(self):
        """Test parsing path without leading slash."""
        result = parse_path_segments('api/v1/teams/')
        assert result == ['api', 'v1', 'teams']

    def test_path_with_trailing_slash(self):
        """Test that trailing slash doesn't create empty segment."""
        result = parse_path_segments('/api/v1/teams/')
        assert result == ['api', 'v1', 'teams']

    def test_path_without_trailing_slash(self):
        """Test path without trailing slash."""
        result = parse_path_segments('/api/v1/teams')
        assert result == ['api', 'v1', 'teams']

    def test_path_with_underscores(self):
        """Test path with underscores in segment names."""
        result = parse_path_segments('/api/v1/http_ports/')
        assert result == ['api', 'v1', 'http_ports']

    def test_path_with_hyphens(self):
        """Test path with hyphens in segment names."""
        result = parse_path_segments('/api/v1/my-resource/')
        assert result == ['api', 'v1', 'my-resource']

    def test_complex_nested_path(self):
        """Test complex nested path with multiple resources."""
        result = parse_path_segments('/api/gateway/v1/orgs/{id}/teams/{pk}/users/')
        assert result == ['api', 'gateway', 'v1', 'orgs', 'teams', 'users']

    def test_placeholder_with_different_names(self):
        """Test placeholders with various parameter names."""
        result = parse_path_segments('/api/v1/teams/{team_id}/users/{user_id}/')
        assert result == ['api', 'v1', 'teams', 'users']


class TestExtractOperationPrefix:
    """Test the extract_operation_prefix function."""

    def test_simple_operation_id(self):
        """Test extracting prefix from simple operation_id."""
        result = extract_operation_prefix('teams_list')
        assert result == 'teams'

    def test_nested_operation_id(self):
        """Test extracting prefix from nested operation_id."""
        result = extract_operation_prefix('teams_users_list')
        assert result == 'teams_users'

    def test_operation_id_with_partial_update(self):
        """Test extracting prefix from partial_update operation_id."""
        result = extract_operation_prefix('teams_partial_update')
        assert result == 'teams'

    def test_nested_operation_id_with_partial_update(self):
        """Test extracting prefix from nested partial_update operation_id."""
        result = extract_operation_prefix('teams_users_partial_update')
        assert result == 'teams_users'

    def test_operation_id_without_underscore(self):
        """Test operation_id without underscore returns itself."""
        result = extract_operation_prefix('retrieve')
        assert result == 'retrieve'

    def test_operation_id_with_create(self):
        """Test extracting prefix from create operation."""
        result = extract_operation_prefix('teams_create')
        assert result == 'teams'

    def test_operation_id_with_retrieve(self):
        """Test extracting prefix from retrieve operation."""
        result = extract_operation_prefix('teams_retrieve')
        assert result == 'teams'

    def test_operation_id_with_update(self):
        """Test extracting prefix from update operation."""
        result = extract_operation_prefix('teams_update')
        assert result == 'teams'

    def test_operation_id_with_destroy(self):
        """Test extracting prefix from destroy operation."""
        result = extract_operation_prefix('teams_destroy')
        assert result == 'teams'

    def test_deeply_nested_operation_id(self):
        """Test extracting prefix from deeply nested operation_id."""
        result = extract_operation_prefix('orgs_teams_users_list')
        assert result == 'orgs_teams_users'

    def test_compound_resource_operation_id(self):
        """Test extracting prefix from compound resource operation_id."""
        result = extract_operation_prefix('http_ports_list')
        assert result == 'http_ports'

    def test_associate_operation_id(self):
        """Test extracting prefix from associate operation_id."""
        result = extract_operation_prefix('http_ports_routes_associate_create')
        assert result == 'http_ports_routes_associate'

    def test_custom_action_operation_id(self):
        """Test extracting prefix from custom action operation_id."""
        result = extract_operation_prefix('settings_getter')
        assert result == 'settings'


class TestExtractOperationAction:
    """Test the extract_operation_action function."""

    def test_list_action(self):
        """Test extracting list action."""
        result = extract_operation_action('teams_list')
        assert result == 'list'

    def test_create_action(self):
        """Test extracting create action."""
        result = extract_operation_action('teams_create')
        assert result == 'create'

    def test_retrieve_action(self):
        """Test extracting retrieve action."""
        result = extract_operation_action('teams_retrieve')
        assert result == 'retrieve'

    def test_update_action(self):
        """Test extracting update action."""
        result = extract_operation_action('teams_update')
        assert result == 'update'

    def test_partial_update_action(self):
        """Test extracting partial_update action."""
        result = extract_operation_action('teams_partial_update')
        assert result == 'partial_update'

    def test_nested_partial_update_action(self):
        """Test extracting partial_update from nested operation_id."""
        result = extract_operation_action('teams_users_partial_update')
        assert result == 'partial_update'

    def test_destroy_action(self):
        """Test extracting destroy action."""
        result = extract_operation_action('teams_destroy')
        assert result == 'destroy'

    def test_custom_action(self):
        """Test extracting custom action."""
        result = extract_operation_action('settings_getter')
        assert result == 'getter'

    def test_action_without_underscore(self):
        """Test operation_id without underscore returns itself."""
        result = extract_operation_action('retrieve')
        assert result == 'retrieve'

    def test_nested_operation_action(self):
        """Test extracting action from nested operation_id."""
        result = extract_operation_action('teams_users_list')
        assert result == 'list'

    def test_deeply_nested_operation_action(self):
        """Test extracting action from deeply nested operation_id."""
        result = extract_operation_action('orgs_teams_users_create')
        assert result == 'create'

    def test_associate_action(self):
        """Test extracting action from associate operation_id."""
        result = extract_operation_action('http_ports_routes_associate_create')
        assert result == 'create'

    def test_compound_resource_action(self):
        """Test extracting action from compound resource."""
        result = extract_operation_action('http_ports_list')
        assert result == 'list'


class TestFilterApiPrefixes:
    """Test the filter_api_prefixes function."""

    def test_filter_with_v1(self):
        """Test filtering with v1 version string."""
        segments = ['api', 'v1', 'teams']
        result = filter_api_prefixes(segments)
        assert result == ['teams']

    def test_filter_with_v2(self):
        """Test filtering with v2 version string."""
        segments = ['api', 'v2', 'users']
        result = filter_api_prefixes(segments)
        assert result == ['users']

    def test_filter_with_gateway_prefix(self):
        """Test filtering with gateway API prefix."""
        segments = ['api', 'gateway', 'v1', 'teams']
        result = filter_api_prefixes(segments)
        assert result == ['teams']

    def test_filter_nested_resources(self):
        """Test filtering with nested resources."""
        segments = ['api', 'v1', 'teams', 'users']
        result = filter_api_prefixes(segments)
        assert result == ['teams', 'users']

    def test_filter_no_version_string(self):
        """Test filtering when no version string present."""
        segments = ['teams', 'users']
        result = filter_api_prefixes(segments)
        assert result == ['teams', 'users']

    def test_filter_multiple_version_strings(self):
        """Test filtering uses last version pattern found."""
        segments = ['api', 'v1', 'internal', 'v2', 'teams']
        result = filter_api_prefixes(segments)
        assert result == ['teams']

    def test_filter_empty_list(self):
        """Test filtering empty list."""
        segments = []
        result = filter_api_prefixes(segments)
        assert result == []

    def test_filter_only_api_prefix(self):
        """Test filtering with only API prefix."""
        segments = ['api', 'v1']
        result = filter_api_prefixes(segments)
        assert result == []

    def test_filter_version_at_end(self):
        """Test filtering with version string at end."""
        segments = ['api', 'v1']
        result = filter_api_prefixes(segments)
        assert result == []

    def test_filter_complex_prefix(self):
        """Test filtering complex API prefix structure."""
        segments = ['api', 'gateway', 'internal', 'v1', 'orgs', 'teams']
        result = filter_api_prefixes(segments)
        assert result == ['orgs', 'teams']

    def test_filter_with_v10(self):
        """Test filtering with double-digit version."""
        segments = ['api', 'v10', 'resources']
        result = filter_api_prefixes(segments)
        assert result == ['resources']

    def test_filter_preserves_order(self):
        """Test that filtering preserves segment order."""
        segments = ['api', 'v1', 'z_resource', 'a_resource', 'b_resource']
        result = filter_api_prefixes(segments)
        assert result == ['z_resource', 'a_resource', 'b_resource']

    def test_filter_non_matching_version_pattern(self):
        """Test that non-matching patterns are not filtered."""
        segments = ['api', 'version1', 'teams']
        result = filter_api_prefixes(segments)
        assert result == ['api', 'version1', 'teams']

    def test_filter_case_sensitive(self):
        """Test that version filtering is case-sensitive."""
        segments = ['api', 'V1', 'teams']
        result = filter_api_prefixes(segments)
        # V1 (uppercase) doesn't match pattern, so nothing filtered
        assert result == ['api', 'V1', 'teams']
