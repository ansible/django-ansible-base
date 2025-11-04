import logging

from ansible_base.api_documentation.preprocessing_hooks import RESOURCE_PURPOSE_MAP, SKIP_AI_DESCRIPTION_PREFIXES, OPERATION_CLASS_MAP

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

# No longer needed - we use a generic "for" preposition for all nested resources
# COMPOUND_RESOURCE_PATTERNS removed in favor of algorithmic approach


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

    For nested resources, uses a generic "for" preposition to indicate the relationship
    without requiring a hardcoded pattern dictionary.

    Args:
        resource_parts: List of resource name parts (e.g., ['teams', 'users'])
        parent_resource: Parent resource name if nested (e.g., 'team')
        action: The action being performed (e.g., 'list', 'create')

    Returns:
        Formatted resource description with prepositions if applicable

    Examples:
        - List /teams/{id}/users/ -> "users for a team"
        - Create /teams/{id}/users/ -> "user for a team"
        - List /http_ports/{id}/routes/ -> "routes for an HTTP port"
    """
    resource_name = ' '.join(resource_parts).replace('_', ' ')

    # Handle nested resources with generic "for" preposition
    if len(resource_parts) >= 2 and parent_resource:
        child_resource = resource_parts[-1]

        # Determine article (a/an) based on parent resource
        article = 'an' if parent_resource[0].lower() in 'aeiou' else 'a'

        # For list actions, use plural child
        if action == 'list':
            return f"{child_resource} for {article} {parent_resource}"
        else:
            # For singular actions, singularize child
            singular_child = singularize_resource(child_resource)
            return f"{singular_child} for {article} {parent_resource}"

    return resource_name


def generate_description_from_purpose(resource_purpose, action, resource_parts, parent_resource):
    """
    Generate x-ai-description from a resource_purpose string.

    Templates are designed to keep descriptions concise and under 200 chars when possible.

    Args:
        resource_purpose: The purpose string from the ViewSet (e.g., "audit trail entries...")
        action: The action being performed (e.g., 'list', 'create', 'retrieve')
        resource_parts: List of resource name parts (e.g., ['teams', 'users'])
        parent_resource: Parent resource name if nested (e.g., 'team')

    Returns:
        Generated x-ai-description string
    """
    # For nested resources, we need to extract just the child resource
    if parent_resource and len(resource_parts) >= 2:
        child_resource = resource_parts[-1]
    else:
        child_resource = resource_parts[-1] if resource_parts else 'resource'

    # Templates optimized for MCP tool understanding
    if action == 'list':
        return f"List {resource_purpose}"
    elif action in ['retrieve', 'read']:
        # Singularize the purpose if it's plural
        singular_purpose = singularize_resource_purpose(resource_purpose)
        return f"Retrieve a {singular_purpose}"
    elif action == 'create':
        singular_purpose = singularize_resource_purpose(resource_purpose)
        return f"Create a {singular_purpose}"
    elif action in ['update', 'partial_update']:
        singular_purpose = singularize_resource_purpose(resource_purpose)
        return f"Update a {singular_purpose}"
    elif action in ['destroy', 'delete']:
        singular_purpose = singularize_resource_purpose(resource_purpose)
        return f"Delete a {singular_purpose}"
    else:
        # For custom actions, just use the purpose as-is
        return resource_purpose


def singularize_resource_purpose(purpose):
    """
    Attempt to singularize a resource_purpose string.

    This handles common patterns like:
    - "audit trail entries for tracking..." -> "audit trail entry for tracking..."
    - "authentication providers for configuring..." -> "authentication provider for configuring..."
    - "user accounts in the AAP platform" -> "user account in the AAP platform"

    The pattern expected is: "<plural noun phrase> <preposition> <context>"
    We singularize only the noun phrase before the preposition.

    Args:
        purpose: The resource purpose string

    Returns:
        Singularized version of the purpose
    """
    # Common prepositions that separate noun phrase from context
    prepositions = [' for ', ' in ', ' of ', ' from ', ' to ', ' with ', ' on ']

    # Try to find a preposition to split on
    for prep in prepositions:
        if prep in purpose:
            # Split on first occurrence to separate noun phrase from context
            parts = purpose.split(prep, 1)
            noun_phrase = parts[0]
            context = parts[1] if len(parts) > 1 else ''

            # Singularize the noun phrase (last word)
            words = noun_phrase.split()
            if words:
                last_word = words[-1]
                singular_last = singularize_resource(last_word)
                words[-1] = singular_last
                singular_noun = ' '.join(words)
            else:
                singular_noun = noun_phrase

            # Reconstruct with preposition
            return f"{singular_noun}{prep}{context}"

    # No preposition found, singularize the last word of the entire string
    words = purpose.split()
    if not words:
        return purpose

    last_word = words[-1]
    singular_last = singularize_resource(last_word)
    words[-1] = singular_last
    return ' '.join(words)


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
    - Respects explicitly defined x-ai-description values (highest priority)
    - Respects skip_ai_description = True on ViewSets/APIViews
    - Uses resource_purpose field for template-based generation (if defined)
    - Falls back to auto-generation from resource names and docstrings
    - Enforces character limits (< 300 chars required, < 200 chars preferred)

    ViewSets can opt-out by setting:
        class MyViewSet(ModelViewSet):
            skip_ai_description = True

    ViewSets can provide purpose-based descriptions by setting:
        class MyViewSet(ModelViewSet):
            resource_purpose = "audit trail entries for tracking system changes"

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

            # Check if this resource has a resource_purpose defined
            # Two-step lookup: operation_id prefix → ViewSet class name → resource_purpose
            # Extract prefix from operation_id (everything before the action)
            if '_partial_update' in operation_id:
                prefix = operation_id.rsplit('_partial_update', 1)[0]
            elif '_' in operation_id:
                prefix = operation_id.rsplit('_', 1)[0]
            else:
                prefix = operation_id

            # Look up ViewSet class name, then resource_purpose
            # OPERATION_CLASS_MAP now stores (class_name, path_parts_count) tuples
            class_info = OPERATION_CLASS_MAP.get(prefix)
            if class_info:
                class_name, _ = class_info  # Extract just the class name from tuple
                resource_purpose = RESOURCE_PURPOSE_MAP.get(class_name)
            else:
                resource_purpose = None
                class_name = None

            # Try to generate description using resource_purpose
            ai_description = None

            # Priority 1: resource_purpose field
            if resource_purpose and action in ['list', 'retrieve', 'read', 'create', 'update', 'partial_update', 'destroy', 'delete']:
                ai_description = generate_description_from_purpose(resource_purpose, action, resource_parts, parent_resource)

            # Priority 2: Fall back to auto-generation logic
            if ai_description is None:
                # Format the resource name with proper grammar
                resource_name = format_compound_resource(resource_parts, parent_resource, action)

                # Get the descriptive operation name
                operation_name = OPERATION_DESCRIPTIVE_NAMES.get(action, action.replace('_', ' ').capitalize())

                # Handle special case: associate/disassociate operations
                # Pattern: {parent}_{child}_{associate|disassociate}_create
                if operation_id.endswith('_associate_create') or operation_id.endswith('_disassociate_create'):
                    is_associate = operation_id.endswith('_associate_create')

                    # Extract parent and child from path (more reliable than operation_id for compound names)
                    # e.g., "/api/gateway/v1/http_ports/{id}/routes/associate/" -> ["http_ports", "routes"]
                    path_parts = [
                        p for p in path.split('/')
                        if p and p not in ['api', 'gateway', 'v1', '{id}', '{pk}', 'associate', 'disassociate']
                    ]

                    if len(path_parts) >= 2:
                        # Last part is the child resource (e.g., "routes", "users", "service_types")
                        child_raw = path_parts[-1]
                        child = child_raw.replace('_', ' ')

                        # Second to last is the parent (e.g., "http_ports", "service_clusters")
                        parent_raw = path_parts[-2]
                        parent_singular = singularize_resource(parent_raw)
                        parent_readable = parent_singular.replace('_', ' ')

                        # Determine article (a/an) based on parent resource
                        article = 'an' if parent_readable[0].lower() in 'aeiou' else 'a'

                        # Generate description
                        if is_associate:
                            ai_description = f"Associate {child} with {article} {parent_readable}"
                        else:
                            ai_description = f"Disassociate {child} from {article} {parent_readable}"
                    else:
                        # Fallback if pattern doesn't match expectations
                        verb = "Associate" if is_associate else "Disassociate"
                        ai_description = f"{verb} {resource_name}"
                # Generate x-ai-description based on action for standard CRUD operations
                # Note: format_compound_resource already handles singular/plural for compound resources
                elif action == 'list':
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
                    base_description = operation.get('description', '').strip()
                    clean_desc = clean_base_description(base_description)
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
