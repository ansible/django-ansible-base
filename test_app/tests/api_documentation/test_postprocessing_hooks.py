"""
Unit tests for api_documentation postprocessing hooks.

These tests verify the behavior of functions used to generate x-ai-description
fields in the OpenAPI spec for MCP (Model Context Protocol) server tools.
"""

from inflection import singularize

from ansible_base.api_documentation.postprocessing_hooks import (
    add_x_ai_description,
    clean_base_description,
    extract_action_and_resource,
    format_compound_resource,
    generate_associate_description,
    generate_crud_description,
    generate_custom_action_description,
    generate_description_from_purpose,
    singularize_resource_purpose,
)
from ansible_base.api_documentation.preprocessing_hooks import OPERATION_CLASS_MAP, RESOURCE_PURPOSE_MAP, SKIP_AI_DESCRIPTION_PREFIXES


class TestExtractActionAndResource:
    """Test the extract_action_and_resource function."""

    def test_simple_list_operation(self):
        """Test extracting action and resource from a simple list operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_list', '/api/gateway/v1/teams/')

        assert action == 'list'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_simple_retrieve_operation(self):
        """Test extracting action and resource from a simple retrieve operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_retrieve', '/api/gateway/v1/teams/{id}/')

        assert action == 'retrieve'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_simple_create_operation(self):
        """Test extracting action and resource from a simple create operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_create', '/api/gateway/v1/teams/')

        assert action == 'create'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_simple_update_operation(self):
        """Test extracting action and resource from a simple update operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_update', '/api/gateway/v1/teams/{id}/')

        assert action == 'update'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_partial_update_operation(self):
        """Test extracting action and resource from a partial_update operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_partial_update', '/api/gateway/v1/teams/{id}/')

        assert action == 'partial_update'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_simple_destroy_operation(self):
        """Test extracting action and resource from a simple destroy operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_destroy', '/api/gateway/v1/teams/{id}/')

        assert action == 'destroy'
        assert resource_parts == ['teams']
        assert parent_resource is None

    def test_nested_resource_list(self):
        """Test extracting action and resource from a nested resource list operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_users_list', '/api/gateway/v1/teams/{id}/users/')

        assert action == 'list'
        assert resource_parts == ['teams', 'users']
        assert parent_resource == 'team'

    def test_nested_resource_create(self):
        """Test extracting action and resource from a nested resource create operation."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_users_create', '/api/gateway/v1/teams/{id}/users/')

        assert action == 'create'
        assert resource_parts == ['teams', 'users']
        assert parent_resource == 'team'

    def test_nested_resource_with_pk(self):
        """Test extracting action and resource when using {pk} instead of {id}."""
        action, resource_parts, parent_resource = extract_action_and_resource('teams_users_list', '/api/gateway/v1/teams/{pk}/users/')

        assert action == 'list'
        assert resource_parts == ['teams', 'users']
        assert parent_resource == 'team'

    def test_compound_resource_name(self):
        """Test extracting action and resource from a compound resource name."""
        action, resource_parts, parent_resource = extract_action_and_resource('http_ports_list', '/api/gateway/v1/http_ports/')

        assert action == 'list'
        assert resource_parts == ['http', 'ports']
        assert parent_resource is None

    def test_nested_compound_resource(self):
        """Test extracting action and resource from a nested compound resource."""
        action, resource_parts, parent_resource = extract_action_and_resource('http_ports_routes_list', '/api/gateway/v1/http_ports/{id}/routes/')

        assert action == 'list'
        assert resource_parts == ['http', 'ports', 'routes']
        assert parent_resource == 'http_port'  # Underscore not yet converted to space

    def test_associate_operation(self):
        """Test extracting action and resource from an associate operation."""
        action, resource_parts, parent_resource = extract_action_and_resource(
            'http_ports_routes_associate_create', '/api/gateway/v1/http_ports/{id}/routes/associate/'
        )

        assert action == 'create'
        assert resource_parts == ['http', 'ports', 'routes', 'associate']
        assert parent_resource == 'http_port'  # Underscore not yet converted to space

    def test_disassociate_operation(self):
        """Test extracting action and resource from a disassociate operation."""
        action, resource_parts, parent_resource = extract_action_and_resource(
            'http_ports_routes_disassociate_create', '/api/gateway/v1/http_ports/{id}/routes/disassociate/'
        )

        assert action == 'create'
        assert resource_parts == ['http', 'ports', 'routes', 'disassociate']
        assert parent_resource == 'http_port'  # Underscore not yet converted to space

    def test_operation_without_underscore(self):
        """Test extracting action and resource from an operation_id without underscores."""
        action, resource_parts, parent_resource = extract_action_and_resource('root_retrieve', '/api/gateway/v1/')

        assert action == 'retrieve'
        assert resource_parts == ['root']
        assert parent_resource is None

    def test_custom_action(self):
        """Test extracting action and resource from a custom action."""
        action, resource_parts, parent_resource = extract_action_and_resource('settings_getter', '/api/gateway/v1/settings/{category_slug}/')

        assert action == 'getter'
        assert resource_parts == ['settings']
        assert parent_resource is None

    def test_fallback_to_path_parsing(self):
        """Test that resource_parts falls back to path parsing if operation_id has no underscores."""
        action, resource_parts, parent_resource = extract_action_and_resource('retrieve', '/api/gateway/v1/teams/')

        # When there's no underscore, resource_parts will be empty initially
        # Then it falls back to parsing the path
        assert action == 'retrieve'
        assert resource_parts == ['teams']  # Falls back to path parsing
        assert parent_resource is None

    def test_deeply_nested_resource(self):
        """Test extracting action and resource from a deeply nested resource (3+ levels)."""
        # Note: This is theoretical - not sure if we have 3+ level nesting in practice
        action, resource_parts, parent_resource = extract_action_and_resource('orgs_teams_users_list', '/api/gateway/v1/orgs/{id}/teams/{id}/users/')

        assert action == 'list'
        assert resource_parts == ['orgs', 'teams', 'users']
        # Parent is extracted from FIRST {id} placeholder, not the last one
        # In practice this edge case likely doesn't occur in our API
        assert parent_resource == 'org'


class TestAddXAiDescription:
    """Test the add_x_ai_description postprocessing hook."""

    def setup_method(self):
        """Clear global state before each test."""
        SKIP_AI_DESCRIPTION_PREFIXES.clear()
        RESOURCE_PURPOSE_MAP.clear()
        OPERATION_CLASS_MAP.clear()

    def test_empty_schema(self):
        """Test that empty schema returns empty schema."""
        result = {}
        modified = add_x_ai_description(result, None, None, None)
        assert modified == {}

    def test_schema_without_paths(self):
        """Test that schema without paths returns unchanged."""
        result = {'info': {'title': 'Test API'}}
        modified = add_x_ai_description(result, None, None, None)
        assert modified == result

    def test_simple_list_operation(self):
        """Test adding x-ai-description to a simple list operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['get']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'List all teams'

    def test_simple_retrieve_operation(self):
        """Test adding x-ai-description to a retrieve operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/': {
                    'get': {
                        'operationId': 'teams_retrieve',
                        'description': 'Retrieve team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/']['get']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Retrieve single team'

    def test_simple_create_operation(self):
        """Test adding x-ai-description to a create operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'post': {
                        'operationId': 'teams_create',
                        'description': 'Create team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['post']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Create new team'

    def test_simple_update_operation(self):
        """Test adding x-ai-description to an update operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/': {
                    'put': {
                        'operationId': 'teams_update',
                        'description': 'Update team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/']['put']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Update existing team'

    def test_partial_update_operation(self):
        """Test adding x-ai-description to a partial update operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/': {
                    'patch': {
                        'operationId': 'teams_partial_update',
                        'description': 'Partial update team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/']['patch']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Partially update existing team'

    def test_simple_destroy_operation(self):
        """Test adding x-ai-description to a destroy operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/': {
                    'delete': {
                        'operationId': 'teams_destroy',
                        'description': 'Delete team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/']['delete']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Delete existing team'

    def test_nested_resource_list(self):
        """Test adding x-ai-description to a nested resource list operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/users/': {
                    'get': {
                        'operationId': 'teams_users_list',
                        'description': 'List users for team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/users/']['get']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'List all users for a team'

    def test_nested_resource_create(self):
        """Test adding x-ai-description to a nested resource create operation."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/users/': {
                    'post': {
                        'operationId': 'teams_users_create',
                        'description': 'Create user for team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/users/']['post']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Create new user for a team'

    def test_associate_operation(self):
        """Test adding x-ai-description to an associate operation."""
        result = {
            'paths': {
                '/api/gateway/v1/http_ports/{id}/routes/associate/': {
                    'post': {
                        'operationId': 'http_ports_routes_associate_create',
                        'description': 'Associate routes',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/http_ports/{id}/routes/associate/']['post']
        assert 'x-ai-description' in operation
        # Note: parent resource has underscore, so 'http port' starts with 'h' not vowel
        assert operation['x-ai-description'] == 'Associate routes with a http port'

    def test_disassociate_operation(self):
        """Test adding x-ai-description to a disassociate operation."""
        result = {
            'paths': {
                '/api/gateway/v1/http_ports/{id}/routes/disassociate/': {
                    'post': {
                        'operationId': 'http_ports_routes_disassociate_create',
                        'description': 'Disassociate routes',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/http_ports/{id}/routes/disassociate/']['post']
        assert 'x-ai-description' in operation
        # Note: parent resource has underscore, so 'http port' starts with 'h' not vowel
        assert operation['x-ai-description'] == 'Disassociate routes from a http port'

    def test_respects_existing_x_ai_description(self):
        """Test that existing x-ai-description is not overwritten."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                        'x-ai-description': 'Custom description',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['get']
        assert operation['x-ai-description'] == 'Custom description'

    def test_respects_skip_ai_description(self):
        """Test that operations with skip_ai_description=True are skipped."""
        # Set up SKIP_AI_DESCRIPTION_PREFIXES
        SKIP_AI_DESCRIPTION_PREFIXES.add('teams')

        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['get']
        assert 'x-ai-description' not in operation

    def test_uses_resource_purpose_for_list(self):
        """Test that resource_purpose is used for list operations."""
        # Set up OPERATION_CLASS_MAP and RESOURCE_PURPOSE_MAP
        OPERATION_CLASS_MAP['teams'] = ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        RESOURCE_PURPOSE_MAP['TeamViewSet'] = 'groups of users working together'

        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['get']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'List groups of users working together'

    def test_uses_resource_purpose_for_retrieve(self):
        """Test that resource_purpose is used and singularized for retrieve operations."""
        # Set up OPERATION_CLASS_MAP and RESOURCE_PURPOSE_MAP
        OPERATION_CLASS_MAP['teams'] = ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        RESOURCE_PURPOSE_MAP['TeamViewSet'] = 'groups of users working together'

        result = {
            'paths': {
                '/api/gateway/v1/teams/{id}/': {
                    'get': {
                        'operationId': 'teams_retrieve',
                        'description': 'Retrieve team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/{id}/']['get']
        assert 'x-ai-description' in operation
        # Should singularize "groups" to "group"
        assert operation['x-ai-description'] == 'Retrieve a group of users working together'

    def test_uses_resource_purpose_for_create(self):
        """Test that resource_purpose is used and singularized for create operations."""
        # Set up OPERATION_CLASS_MAP and RESOURCE_PURPOSE_MAP
        OPERATION_CLASS_MAP['teams'] = ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        RESOURCE_PURPOSE_MAP['TeamViewSet'] = 'groups of users working together'

        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'post': {
                        'operationId': 'teams_create',
                        'description': 'Create team',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['post']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'Create a group of users working together'

    def test_custom_action_with_description(self):
        """Test custom action uses operation description."""
        result = {
            'paths': {
                '/api/gateway/v1/settings/{category_slug}/': {
                    'get': {
                        'operationId': 'settings_getter',
                        'description': 'A view class for managing and displaying a group of settings for a specific category.',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/settings/{category_slug}/']['get']
        assert 'x-ai-description' in operation
        # Should clean the description and use first sentence
        assert 'Getter' in operation['x-ai-description']
        assert len(operation['x-ai-description']) <= 200

    def test_enforces_300_char_limit(self):
        """Test that x-ai-description is truncated if it exceeds 300 characters."""
        # Create a very long resource_purpose
        long_purpose = 'a' * 400

        OPERATION_CLASS_MAP['teams'] = ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        RESOURCE_PURPOSE_MAP['TeamViewSet'] = long_purpose

        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/teams/']['get']
        assert 'x-ai-description' in operation
        assert len(operation['x-ai-description']) == 300
        assert operation['x-ai-description'].endswith('...')

    def test_skips_non_operation_keys(self):
        """Test that non-operation keys like 'parameters' are skipped."""
        result = {
            'paths': {
                '/api/gateway/v1/teams/': {
                    'parameters': [{'name': 'id', 'in': 'path'}],
                    'get': {
                        'operationId': 'teams_list',
                        'description': 'List teams',
                    },
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        # Should not raise any errors
        assert 'parameters' in result['paths']['/api/gateway/v1/teams/']
        assert 'x-ai-description' not in result['paths']['/api/gateway/v1/teams/']['parameters'][0]
        assert 'x-ai-description' in result['paths']['/api/gateway/v1/teams/']['get']

    def test_compound_resource_name(self):
        """Test handling of compound resource names like http_ports."""
        result = {
            'paths': {
                '/api/gateway/v1/http_ports/': {
                    'get': {
                        'operationId': 'http_ports_list',
                        'description': 'List HTTP ports',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/http_ports/']['get']
        assert 'x-ai-description' in operation
        assert operation['x-ai-description'] == 'List all http ports'

    def test_nested_compound_resource(self):
        """Test handling of nested compound resource names."""
        result = {
            'paths': {
                '/api/gateway/v1/http_ports/{id}/routes/': {
                    'get': {
                        'operationId': 'http_ports_routes_list',
                        'description': 'List routes for HTTP port',
                    }
                }
            }
        }

        add_x_ai_description(result, None, None, None)

        operation = result['paths']['/api/gateway/v1/http_ports/{id}/routes/']['get']
        assert 'x-ai-description' in operation
        # Note: parent resource has underscore, so 'http_port' starts with 'h' not vowel
        assert operation['x-ai-description'] == 'List all routes for a http_port'


class TestHelperFunctions:
    """Test helper functions used by add_x_ai_description."""

    def test_singularize_resource_standard_plural(self):
        """Test singularizing standard plural forms."""
        assert singularize('teams') == 'team'
        assert singularize('users') == 'user'
        assert singularize('routes') == 'route'

    def test_singularize_resource_ies_ending(self):
        """Test singularizing words ending in 'ies'."""
        assert singularize('categories') == 'category'
        assert singularize('entries') == 'entry'

    def test_singularize_resource_ses_ending(self):
        """Test singularizing words ending in 'ses'."""
        assert singularize('addresses') == 'address'

    def test_singularize_resource_irregular(self):
        """Test singularizing irregular plurals."""
        assert singularize('status') == 'status'
        assert singularize('data') == 'datum'

    def test_singularize_resource_already_singular(self):
        """Test that already singular words are unchanged."""
        assert singularize('team') == 'team'
        assert singularize('port') == 'port'

    def test_singularize_resource_purpose_with_preposition(self):
        """Test singularizing resource_purpose with prepositions."""
        assert singularize_resource_purpose('audit trail entries for tracking changes') == 'audit trail entry for tracking changes'
        assert singularize_resource_purpose('authentication providers for configuring SSO') == 'authentication provider for configuring SSO'

    def test_singularize_resource_purpose_without_preposition(self):
        """Test singularizing resource_purpose without prepositions."""
        assert singularize_resource_purpose('audit trail entries') == 'audit trail entry'
        assert singularize_resource_purpose('user accounts') == 'user account'

    def test_format_compound_resource_simple(self):
        """Test formatting simple resource names."""
        result = format_compound_resource(['teams'], None, 'list')
        assert result == 'teams'

        result = format_compound_resource(['http_ports'], None, 'list')
        assert result == 'http ports'

    def test_format_compound_resource_nested_list(self):
        """Test formatting nested resource names for list actions."""
        result = format_compound_resource(['teams', 'users'], 'team', 'list')
        assert result == 'users for a team'

    def test_format_compound_resource_nested_singular(self):
        """Test formatting nested resource names for singular actions."""
        result = format_compound_resource(['teams', 'users'], 'team', 'create')
        assert result == 'user for a team'

    def test_format_compound_resource_article_an(self):
        """Test that 'an' is used for vowel-starting parent resources."""
        result = format_compound_resource(['organizations', 'teams'], 'organization', 'list')
        assert result == 'teams for an organization'

    def test_generate_description_from_purpose_list(self):
        """Test generating description from purpose for list action."""
        result = generate_description_from_purpose('groups of users', 'list')
        assert result == 'List groups of users'

    def test_generate_description_from_purpose_retrieve(self):
        """Test generating description from purpose for retrieve action."""
        result = generate_description_from_purpose('groups of users', 'retrieve')
        assert result == 'Retrieve a group of users'

    def test_generate_description_from_purpose_create(self):
        """Test generating description from purpose for create action."""
        result = generate_description_from_purpose('groups of users', 'create')
        assert result == 'Create a group of users'

    def test_generate_description_from_purpose_unknown_action(self):
        """Test generating description from purpose for unknown action."""
        result = generate_description_from_purpose('groups of users', 'custom_action')
        # Should return purpose as-is
        assert result == 'groups of users'

    def test_clean_base_description_removes_prefixes(self):
        """Test that common prefixes are removed from base descriptions."""
        assert clean_base_description('API endpoint that allows users to log in') == 'users to log in'
        assert clean_base_description('API endpoint for managing teams') == 'managing teams'
        assert (
            clean_base_description('A view class for managing and displaying a group of settings for a specific category.')
            == 'a group of settings for a specific category'
        )

    def test_clean_base_description_removes_trailing_period(self):
        """Test that trailing period is removed."""
        assert clean_base_description('Manage teams.') == 'Manage teams'

    def test_clean_base_description_handles_multiline(self):
        """Test that multiline descriptions are concatenated into a single sentence."""
        multiline = "First line.\nSecond line.\nThird line."
        result = clean_base_description(multiline)
        assert result == 'First line'

    def test_generate_crud_description_list(self):
        """Test generating CRUD description for list action."""
        result = generate_crud_description('list', 'List all', 'teams', None)
        assert result == 'List all teams'

    def test_generate_crud_description_retrieve(self):
        """Test generating CRUD description for retrieve action."""
        result = generate_crud_description('retrieve', 'Retrieve single', 'teams', None)
        assert result == 'Retrieve single team'

    def test_generate_crud_description_nested(self):
        """Test generating CRUD description for nested resource."""
        result = generate_crud_description('list', 'List all', 'users for a team', 'team')
        assert result == 'List all users for a team'

    def test_generate_crud_description_unknown_action(self):
        """Test generating CRUD description for unknown action returns None."""
        result = generate_crud_description('custom_action', 'Custom action', 'teams', None)
        assert result is None

    def test_generate_associate_description_associate(self):
        """Test generating description for associate operation."""
        result = generate_associate_description('http_ports_routes_associate_create', '/api/gateway/v1/http_ports/{id}/routes/associate/', 'routes')
        # Note: parent resource has underscore replaced with space, so 'http port' starts with 'h' not vowel
        assert result == 'Associate routes with a http port'

    def test_generate_associate_description_disassociate(self):
        """Test generating description for disassociate operation."""
        result = generate_associate_description('http_ports_routes_disassociate_create', '/api/gateway/v1/http_ports/{id}/routes/disassociate/', 'routes')
        # Note: parent resource has underscore replaced with space, so 'http port' starts with 'h' not vowel
        assert result == 'Disassociate routes from a http port'

    def test_generate_custom_action_description_with_clean_desc(self):
        """Test generating description for custom action with clean description."""
        operation = {'description': 'API endpoint that allows users to log in'}
        result = generate_custom_action_description('Custom', 'teams', operation)
        assert result == 'Custom users to log in'

    def test_generate_custom_action_description_without_desc(self):
        """Test generating description for custom action without description."""
        operation = {}
        result = generate_custom_action_description('Custom', 'teams', operation)
        assert result == 'Custom teams'
