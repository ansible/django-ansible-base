import logging

from ansible_base.api_documentation.path_utils import (
    extract_operation_action,
    extract_operation_prefix,
    filter_api_prefixes,
    parse_path_segments,
)
from ansible_base.api_documentation.preprocessing_hooks import OPERATION_CLASS_MAP, RESOURCE_PURPOSE_MAP, SKIP_AI_DESCRIPTION_PREFIXES

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


def singularize_resource(resource_name):
    """Convert resource name to singular form, handling irregular plurals."""
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


def _extract_resource_parts_from_operation_id(operation_id, action):
    """Extract resource parts from operation_id by removing the action suffix."""
    # Handle special case of "partial_update" which has two underscores
    if action == 'partial_update' and '_partial_update' in operation_id:
        return operation_id.split('_')[:-2] if operation_id.count('_') >= 2 else []

    # Standard case: remove the last segment (the action)
    if '_' in operation_id:
        return operation_id.split('_')[:-1]

    return []


def _has_segments_after_placeholder(parts, placeholder_index):
    """Check if there are non-placeholder resource segments after a placeholder."""
    remaining_parts = [p for p in parts[placeholder_index + 1 :] if p and not p.startswith('{')]
    return bool(remaining_parts)


def _extract_parent_from_prefix(parts, placeholder_index):
    """Extract parent resource name (singular) from path segments before a placeholder."""
    parent_prefix = '/'.join(parts[: placeholder_index + 1])
    parent_segments = parse_path_segments(parent_prefix)

    if parent_segments:
        return singularize_resource(parent_segments[-1])

    return None


def _find_parent_resource_from_path(path, placeholders=None):
    """
    Find parent resource in nested REST path by detecting placeholders with segments after.
    Returns singular parent resource name or None if not nested.
    """
    if placeholders is None:
        placeholders = ['{id}', '{pk}']

    # Check if any placeholder exists in the path
    if not any(placeholder in path for placeholder in placeholders):
        return None

    # Split path into segments
    parts = path.split('/')

    # Find the first parameter placeholder
    placeholder_index = next((i for i, part in enumerate(parts) if part in placeholders), -1)

    if placeholder_index == -1:
        return None

    # Check if there are resource segments after the placeholder
    if not _has_segments_after_placeholder(parts, placeholder_index):
        return None  # Not truly nested

    # Extract and return parent resource name
    return _extract_parent_from_prefix(parts, placeholder_index)


def extract_action_and_resource(operation_id, path):
    """
    Extract action, resource parts, and parent resource from operation_id and path.
    Returns: (action, resource_parts, parent_resource)
    """
    # Extract action using utility function
    action = extract_operation_action(operation_id)

    # Extract resource parts from operation_id
    resource_parts = _extract_resource_parts_from_operation_id(operation_id, action)

    # Detect parent-child relationships from path
    parent_resource = _find_parent_resource_from_path(path)

    # Fallback to extracting from path if no resource_parts
    if not resource_parts:
        path_parts = parse_path_segments(path)
        resource_parts = [path_parts[-1]] if path_parts else ['resource']

    return action, resource_parts, parent_resource


def format_compound_resource(resource_parts, parent_resource, action):
    """
    Format compound resource names with proper prepositions for nested resources.
    E.g., "users for a team", "route for an HTTP port"
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


def generate_description_from_purpose(resource_purpose, action):
    """Generate x-ai-description from resource_purpose using action templates."""
    # Templates optimized for MCP tool understanding
    action_templates = {
        'list': lambda p: f"List {p}",
        'retrieve': lambda p: f"Retrieve a {singularize_resource_purpose(p)}",
        'read': lambda p: f"Retrieve a {singularize_resource_purpose(p)}",
        'create': lambda p: f"Create a {singularize_resource_purpose(p)}",
        'update': lambda p: f"Update a {singularize_resource_purpose(p)}",
        'partial_update': lambda p: f"Update a {singularize_resource_purpose(p)}",
        'destroy': lambda p: f"Delete a {singularize_resource_purpose(p)}",
        'delete': lambda p: f"Delete a {singularize_resource_purpose(p)}",
    }

    template = action_templates.get(action)
    return template(resource_purpose) if template else resource_purpose


def singularize_resource_purpose(purpose):
    """
    Singularize resource_purpose by finding prepositions and singularizing the noun phrase before.
    E.g., "audit trail entries for tracking..." -> "audit trail entry for tracking..."
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


def generate_associate_description(operation_id, path, resource_name):
    """Generate description for associate/disassociate operations."""
    is_associate = operation_id.endswith('_associate_create')

    # Filter out API prefixes (everything up to version string) using generic approach
    path_parts = filter_api_prefixes(parse_path_segments(path))

    # Remove associate/disassociate if it's the last segment (special action marker)
    if path_parts and path_parts[-1] in ['associate', 'disassociate']:
        path_parts = path_parts[:-1]

    if len(path_parts) >= 2:
        child = path_parts[-1].replace('_', ' ')
        parent_singular = singularize_resource(path_parts[-2])
        parent_readable = parent_singular.replace('_', ' ')
        article = 'an' if parent_readable[0].lower() in 'aeiou' else 'a'

        verb = "Associate" if is_associate else "Disassociate"
        preposition = "with" if is_associate else "from"
        return f"{verb} {child} {preposition} {article} {parent_readable}"

    # Fallback if pattern doesn't match
    verb = "Associate" if is_associate else "Disassociate"
    return f"{verb} {resource_name}"


def generate_crud_description(action, operation_name, resource_name, parent_resource):
    """Generate description for standard CRUD operations."""
    # For list operations, use the name as-is (already formatted)
    if action == 'list':
        return f"{operation_name} {resource_name}"

    # For partial_update, use special formatting
    if action == 'partial_update':
        if parent_resource:
            return f"Partially update existing {resource_name}"
        return f"Partially update existing {singularize_resource(resource_name)}"

    # For other CRUD operations (retrieve, read, create, update, destroy, delete)
    if action in ['retrieve', 'read', 'create', 'update', 'destroy', 'delete']:
        if parent_resource:
            # Compound resources already formatted
            return f"{operation_name} {resource_name}"
        # Simple resources need singularization
        return f"{operation_name} {singularize_resource(resource_name)}"

    return None  # Indicate that this isn't a standard CRUD operation


def generate_custom_action_description(operation_name, resource_name, operation):
    """Generate description for custom actions."""
    base_description = operation.get('description', '').strip()
    clean_desc = clean_base_description(base_description)
    return f"{operation_name} {clean_desc}" if clean_desc else f"{operation_name} {resource_name}"


def clean_base_description(description):
    """Clean up base description by removing common boilerplate."""
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
            clean_desc = clean_desc[len(prefix) :].strip()
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


def _should_skip_operation(method):
    """Check if a method key should be skipped (is not an HTTP operation)."""
    return method not in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']


def _should_skip_ai_description(operation_id):
    """Check if an operation should skip AI description generation."""
    if not operation_id:
        return False

    prefix = operation_id.split('_')[0] if '_' in operation_id else operation_id
    if prefix in SKIP_AI_DESCRIPTION_PREFIXES:
        return True
    return False


def _lookup_resource_purpose(operation_id):
    """Look up resource_purpose for an operation via its prefix and ViewSet class."""
    prefix = extract_operation_prefix(operation_id)
    class_info = OPERATION_CLASS_MAP.get(prefix)

    if not class_info:
        return None, None

    class_name, _, _ = class_info  # Extract class name from (class_name, path_parts_count, path_parts) tuple
    resource_purpose = RESOURCE_PURPOSE_MAP.get(class_name)
    return resource_purpose, class_name


def _generate_from_resource_purpose(resource_purpose, action):
    """Generate description from resource_purpose if action is supported."""
    if not resource_purpose:
        return None

    if action in ['list', 'retrieve', 'read', 'create', 'update', 'partial_update', 'destroy', 'delete']:
        return generate_description_from_purpose(resource_purpose, action)

    return None


def _generate_description_auto(operation_id, action, resource_parts, parent_resource, path, operation):
    """Auto-generate description from resource names and operation type."""
    # Format the resource name with proper grammar
    resource_name = format_compound_resource(resource_parts, parent_resource, action)

    # Get the descriptive operation name
    operation_name = OPERATION_DESCRIPTIVE_NAMES.get(action, action.replace('_', ' ').capitalize())

    # Handle associate/disassociate operations
    if operation_id.endswith('_associate_create') or operation_id.endswith('_disassociate_create'):
        return generate_associate_description(operation_id, path, resource_name)

    # Try standard CRUD operation
    ai_description = generate_crud_description(action, operation_name, resource_name, parent_resource)

    # Fall back to custom action if not CRUD
    if ai_description is None:
        ai_description = generate_custom_action_description(operation_name, resource_name, operation)

    return ai_description


def _enforce_character_limit(description, max_length=300):
    """Enforce character limit on description, truncating if necessary."""
    if len(description) > max_length:
        return description[: max_length - 3] + "..."
    return description


def _process_operation(operation, method, path):
    """Process a single operation to add x-ai-description (modifies operation in-place)."""
    # Skip if already has x-ai-description (respect explicit definitions)
    if 'x-ai-description' in operation:
        logger.debug(f"x-ai-description already defined for {path} {method.upper()}. Respecting existing value.")
        return

    # Get operation ID
    operation_id = operation.get('operationId', '')

    # Check if the ViewSet has opted out of AI description generation
    if _should_skip_ai_description(operation_id):
        return

    # Extract action, resource parts, and parent resource
    action, resource_parts, parent_resource = extract_action_and_resource(operation_id, path)

    # Try to generate description with priority order:
    # 1. resource_purpose field (if defined on ViewSet)
    # 2. Auto-generation from resource names and operation type

    # Priority 1: Check for resource_purpose
    resource_purpose, _ = _lookup_resource_purpose(operation_id)
    ai_description = _generate_from_resource_purpose(resource_purpose, action)

    # Priority 2: Fall back to auto-generation
    if ai_description is None:
        ai_description = _generate_description_auto(operation_id, action, resource_parts, parent_resource, path, operation)

    # Enforce character limit and add to operation
    operation['x-ai-description'] = _enforce_character_limit(ai_description)


def add_x_ai_description(result, generator, request, public):
    """
    Postprocessing hook for drf-spectacular that adds x-ai-description fields to all operations.

    This hook runs after OpenAPI schema generation and automatically generates x-ai-description
    fields for all API operations. These descriptions are used by MCP (Model Context Protocol)
    servers to provide better context to AI tools when selecting which API endpoints to call.

    The hook uses a three-tier priority system for generating descriptions:
    1. Explicit x-ai-description - If defined via @extend_schema, use as-is (highest priority)
    2. resource_purpose field - Generate from ViewSet's resource_purpose using action templates
    3. Auto-generation - Generate from resource names, operation types, and docstrings (fallback)

    ViewSets can opt out of automatic generation by setting skip_ai_description = True.
    ViewSets can provide custom purpose-based descriptions by defining a resource_purpose field.

    All generated descriptions are enforced to be under 300 characters (with 200 preferred).

    Example ViewSet configurations:

        # Opt out of AI description generation
        class MyViewSet(ModelViewSet):
            skip_ai_description = True

        # Provide purpose-based descriptions for CRUD operations
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
            if _should_skip_operation(method):
                continue

            # Process this operation to add x-ai-description
            _process_operation(operation, method, path)

    return result
