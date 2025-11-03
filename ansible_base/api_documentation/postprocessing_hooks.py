import logging
import re

from ansible_base.api_documentation.preprocessing_hooks import SKIP_AI_DESCRIPTION_PREFIXES

logger = logging.getLogger('ansible_base.api_documentation.postprocessing_hooks')

# Operation name mappings for different HTTP methods and actions
OPERATION_DESCRIPTIVE_NAMES = {
    'list': 'List all',
    'create': 'Create new',
    'retrieve': 'Retrieve single',
    'read': 'Retrieve single',
    'update': 'Update existing',
    'partial_update': 'Partially update existing',
    'destroy': 'Delete existing',
    'delete': 'Delete existing',
}

# Irregular plurals that shouldn't have 's' stripped
IRREGULAR_PLURALS = {
    'status': 'status',  # status -> status (same singular/plural)
    'data': 'datum',
    'criteria': 'criterion',
    'analysis': 'analysis',
    'basis': 'basis',
}

# Common compound resource patterns that need prepositions
# Pattern: (parent_resource, child_resource) -> preposition
COMPOUND_RESOURCE_PATTERNS = {
    ('team', 'user'): 'in a',
    ('user', 'team'): 'for a',
    ('organization', 'user'): 'in an',
    ('organization', 'team'): 'in an',
    ('http port', 'route'): 'for an',
    ('authenticator', 'map'): 'for an',
}


def singularize_resource(resource_name):
    """
    Convert a resource name to singular form, handling irregular plurals.

    Args:
        resource_name: The resource name to singularize (e.g., 'teams', 'status')

    Returns:
        The singular form of the resource name
    """
    # Check for irregular plurals first
    if resource_name in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[resource_name]

    # Handle common patterns
    if resource_name.endswith('ies'):
        # e.g., 'categories' -> 'category'
        return resource_name[:-3] + 'y'
    elif resource_name.endswith('ses'):
        # e.g., 'addresses' -> 'address'
        return resource_name[:-2]
    elif resource_name.endswith('s') and len(resource_name) > 1:
        # Standard plural: just remove 's'
        return resource_name[:-1]

    # Already singular or unknown pattern
    return resource_name


def extract_action_and_resource(operation_id, path):
    """
    Extract the action and resource parts from an operation_id.

    Args:
        operation_id: The operation ID (e.g., 'teams_users_list')
        path: The URL path (e.g., '/api/gateway/v1/teams/{id}/users/')

    Returns:
        Tuple of (action, resource_parts, parent_resource)
    """
    # Handle special cases like "partial_update"
    if '_partial_update' in operation_id:
        action = 'partial_update'
        resource_parts = operation_id.split('_')[:-2] if operation_id.count('_') >= 2 else []
    elif '_' in operation_id:
        action = operation_id.split('_')[-1]
        resource_parts = operation_id.split('_')[:-1]
    else:
        action = 'get'  # fallback
        resource_parts = []

    # Detect parent-child relationships from path
    # e.g., /teams/{id}/users/ -> parent='team', child='user'
    parent_resource = None
    if '{id}' in path or '{pk}' in path:
        # This is a nested resource - check if there are segments after the {id}
        # Split path and find the {id} or {pk}
        parts = path.split('/')

        # Find index of {id} or {pk}
        id_index = -1
        for i, part in enumerate(parts):
            if part in ['{id}', '{pk}']:
                id_index = i
                break

        # If there are path segments AFTER the {id}, then this is a nested resource
        # e.g., /teams/{id}/users/ -> ['', 'api', 'gateway', 'v1', 'teams', '{id}', 'users', '']
        remaining_parts = [p for p in parts[id_index+1:] if p and not p.startswith('{')]

        if remaining_parts:
            # This is truly nested - the parent is the segment before {id}
            parent_segments = [p for p in parts[:id_index] if p and not p.startswith('{')]
            if parent_segments:
                parent_resource = singularize_resource(parent_segments[-1])

    # Fallback to extracting from path if no resource_parts
    if not resource_parts:
        path_parts = [p for p in path.split('/') if p and not p.startswith('{')]
        resource_parts = [path_parts[-1]] if path_parts else ['resource']

    return action, resource_parts, parent_resource


def format_compound_resource(resource_parts, parent_resource, action):
    """
    Format compound resource names with proper prepositions.

    Args:
        resource_parts: List of resource name parts (e.g., ['teams', 'users'])
        parent_resource: Parent resource name if nested (e.g., 'team')
        action: The action being performed (e.g., 'list', 'create')

    Returns:
        Formatted resource description with prepositions if applicable
    """
    resource_name = ' '.join(resource_parts).replace('_', ' ')

    # Handle compound resources (e.g., "teams users" -> "users in a team")
    if len(resource_parts) >= 2 and parent_resource:
        child_resource = resource_parts[-1]

        # Check if we have a pattern match
        pattern_key = (parent_resource, singularize_resource(child_resource))
        if pattern_key in COMPOUND_RESOURCE_PATTERNS:
            preposition = COMPOUND_RESOURCE_PATTERNS[pattern_key]

            # For list actions, use plural child
            if action == 'list':
                return f"{child_resource} {preposition} {parent_resource}"
            else:
                # For singular actions, singularize both
                singular_child = singularize_resource(child_resource)
                return f"{singular_child} {preposition} {parent_resource}"

    return resource_name


def clean_base_description(description):
    """
    Clean up base description by removing common boilerplate.

    Args:
        description: The base description from the ViewSet/APIView

    Returns:
        Cleaned description string
    """
    if not description:
        return ""

    clean_desc = description.strip()

    # Remove common prefixes
    prefixes_to_remove = [
        'API endpoint that allows',
        'API endpoint that',
        'API endpoint for',
        'A view class for managing and displaying',
        'Endpoint:',
    ]

    for prefix in prefixes_to_remove:
        if clean_desc.startswith(prefix):
            clean_desc = clean_desc[len(prefix):].strip()
            break

    # Remove trailing period
    if clean_desc.endswith('.'):
        clean_desc = clean_desc[:-1]

    # If description is too long or contains multiple sentences, truncate
    # This handles cases like settings_getter where entire docstring was used
    if len(clean_desc) > 100 or '\n' in clean_desc:
        # Take first sentence or first 100 chars
        first_line = clean_desc.split('\n')[0]
        if '.' in first_line[:100]:
            clean_desc = first_line.split('.')[0]
        else:
            clean_desc = first_line[:100]

    return clean_desc.strip()


def add_x_ai_description(result, generator, request, public):
    """
    Postprocessing hook for drf-spectacular that adds x-ai-description to all operations.

    This hook:
    - Respects explicitly defined x-ai-description values
    - Respects skip_ai_description = True on ViewSets/APIViews
    - Auto-generates descriptions by prepending operation type to existing descriptions
    - Enforces character limits (< 300 chars required, < 200 chars preferred)
    - Logs warnings when descriptions need manual review

    ViewSets can opt-out by setting:
        class MyViewSet(ModelViewSet):
            skip_ai_description = True

    Args:
        result: The generated OpenAPI schema dictionary
        generator: The SchemaGenerator instance
        request: The HTTP request (if available)
        public: Boolean indicating if this is for public schema

    Returns:
        The modified schema dictionary with x-ai-description fields added
    """
    paths = result.get('paths', {})

    for path, path_item in paths.items():
        for method, operation in path_item.items():
            # Skip non-operation keys (like 'parameters')
            if method not in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
                continue

            # Check if the view has opted out of x-ai-description generation
            # Check operation_id prefix against skip list
            operation_id = operation.get('operationId', '')
            if operation_id:
                # Extract prefix (e.g., "teams_list" -> "teams")
                prefix = operation_id.split('_')[0] if '_' in operation_id else operation_id
                if prefix in SKIP_AI_DESCRIPTION_PREFIXES:
                    logger.debug(
                        f"Operation {operation_id} has skip_ai_description=True (prefix: {prefix}). "
                        f"Skipping x-ai-description generation."
                    )
                    continue

            # Skip if already has x-ai-description
            if 'x-ai-description' in operation:
                logger.debug(
                    f"x-ai-description already defined for {path} {method.upper()}. "
                    f"Respecting existing value."
                )
                continue

            # Get operation ID to determine action
            operation_id = operation.get('operationId', '')

            # Extract action, resource parts, and parent resource
            action, resource_parts, parent_resource = extract_action_and_resource(operation_id, path)

            # Format the resource name with proper grammar
            resource_name = format_compound_resource(resource_parts, parent_resource, action)

            # Get the descriptive operation name
            operation_name = OPERATION_DESCRIPTIVE_NAMES.get(action, action.replace('_', ' ').capitalize())

            # Get existing description (if available, use it for context)
            base_description = operation.get('description', '').strip()
            clean_desc = clean_base_description(base_description)

            # Generate x-ai-description based on action
            # Note: format_compound_resource already handles singular/plural for compound resources
            if action == 'list':
                # Use plural/formatted name as-is
                ai_description = f"{operation_name} {resource_name}"
            elif action in ['retrieve', 'read']:
                # Singularize only if it's not a compound resource
                if parent_resource:
                    # Already formatted by format_compound_resource
                    ai_description = f"{operation_name} {resource_name}"
                else:
                    singular_name = singularize_resource(resource_name)
                    ai_description = f"{operation_name} {singular_name}"
            elif action in ['create', 'update', 'destroy', 'delete']:
                # Singularize only if it's not a compound resource
                if parent_resource:
                    # Already formatted by format_compound_resource
                    ai_description = f"{operation_name} {resource_name}"
                else:
                    singular_name = singularize_resource(resource_name)
                    ai_description = f"{operation_name} {singular_name}"
            elif action == 'partial_update':
                # Singularize only if it's not a compound resource
                if parent_resource:
                    ai_description = f"Partially update existing {resource_name}"
                else:
                    singular_name = singularize_resource(resource_name)
                    ai_description = f"Partially update existing {singular_name}"
            else:
                # For custom actions, include the cleaned description if available
                if clean_desc:
                    ai_description = f"{operation_name} {clean_desc}"
                else:
                    ai_description = f"{operation_name} {resource_name}"

            # Enforce character limit
            if len(ai_description) > 300:
                ai_description = ai_description[:297] + "..."

            # Add to operation
            operation['x-ai-description'] = ai_description

    return result
