"""
Utility functions for parsing API paths and operation IDs.

This module provides shared utilities used by both preprocessing and
postprocessing hooks to ensure consistent path parsing logic.
"""


def parse_path_segments(path):
    """
    Parse URL path into clean segments, excluding parameter placeholders.

    This handles both Django URL patterns (<pk>, <int:pk>) and OpenAPI
    format ({id}, {pk}) consistently.

    Args:
        path: URL path string (e.g., '/api/gateway/v1/teams/{id}/users/')

    Returns:
        List of path segments excluding parameters
        (e.g., ['api', 'gateway', 'v1', 'teams', 'users'])

    Examples:
        >>> parse_path_segments('/api/gateway/v1/teams/')
        ['api', 'gateway', 'v1', 'teams']

        >>> parse_path_segments('/api/gateway/v1/teams/{id}/users/')
        ['api', 'gateway', 'v1', 'teams', 'users']

        >>> parse_path_segments('/api/gateway/v1/teams/<pk>/users/')
        ['api', 'gateway', 'v1', 'teams', 'users']
    """
    # Filter out empty strings and path parameters (both {id} and <pk> formats)
    return [p for p in path.split('/') if p and not p.startswith(('<', '{'))]


def extract_operation_prefix(operation_id):
    """
    Extract the resource prefix from an operation_id.

    The prefix is everything before the final action (e.g., 'list', 'create').
    Handles special case of 'partial_update' action.

    Args:
        operation_id: The operation ID (e.g., 'teams_users_list')

    Returns:
        The prefix string (e.g., 'teams_users')

    Examples:
        >>> extract_operation_prefix('teams_list')
        'teams'

        >>> extract_operation_prefix('teams_users_list')
        'teams_users'

        >>> extract_operation_prefix('teams_partial_update')
        'teams'

        >>> extract_operation_prefix('status_retrieve')
        'status'
    """
    if '_partial_update' in operation_id:
        return operation_id.rsplit('_partial_update', 1)[0]
    elif '_' in operation_id:
        return operation_id.rsplit('_', 1)[0]
    else:
        return operation_id


def extract_operation_action(operation_id):
    """
    Extract the action from an operation_id.

    Args:
        operation_id: The operation ID (e.g., 'teams_users_list')

    Returns:
        The action string (e.g., 'list', 'create', 'partial_update')

    Examples:
        >>> extract_operation_action('teams_list')
        'list'

        >>> extract_operation_action('teams_partial_update')
        'partial_update'

        >>> extract_operation_action('users_create')
        'create'
    """
    if '_partial_update' in operation_id:
        return 'partial_update'
    elif '_' in operation_id:
        return operation_id.split('_')[-1]
    else:
        # No underscore - this is likely a custom action or edge case
        return operation_id
