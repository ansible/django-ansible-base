import logging

from ansible_base.api_documentation.path_utils import parse_path_segments

logger = logging.getLogger('ansible_base.api_documentation.preprocessing_hooks')

# Global storage for skip_ai_description operation ID prefixes
# Maps operation_id prefix (e.g. "teams") -> True for views with skip_ai_description
# This is shared with postprocessing_hooks.py
SKIP_AI_DESCRIPTION_PREFIXES = set()

# Global storage for resource_purpose values
# Maps ViewSet class name -> resource_purpose string
# This is shared with postprocessing_hooks.py
RESOURCE_PURPOSE_MAP = {}

# Global storage for ViewSet class names by operation_id prefix
# Maps operation_id prefix (e.g. "authenticators") -> (ViewSet class name, path_parts_count)
# This is shared with postprocessing_hooks.py
# We store the count to resolve collisions: fewer path parts = main resource, gets simple prefix
OPERATION_CLASS_MAP = {}


def mark_skip_ai_description(endpoints, **kwargs):
    """
    Preprocessing hook that identifies views with skip_ai_description = True
    and extracts resource_purpose values.

    This stores ViewSet class names and resource purposes globally so the
    postprocessing hook can use them when generating x-ai-description fields.

    Preprocessing hooks receive: endpoints list
    """
    global SKIP_AI_DESCRIPTION_PREFIXES, RESOURCE_PURPOSE_MAP, OPERATION_CLASS_MAP
    SKIP_AI_DESCRIPTION_PREFIXES.clear()
    RESOURCE_PURPOSE_MAP.clear()
    OPERATION_CLASS_MAP.clear()

    if not endpoints:
        return endpoints

    for path, path_regex, method, view in endpoints:
        try:
            if hasattr(view, 'cls'):
                view_class = view.cls
            else:
                view_class = view.__class__

            class_name = view_class.__name__

            # Extract the resource prefix from the path
            # This will be used as the operation_id prefix by drf-spectacular
            # e.g., /api/gateway/v1/teams/ -> "teams"
            # e.g., /api/gateway/v1/users/{id}/teams/ -> "users_teams"
            path_parts = parse_path_segments(path)
            if not path_parts:
                continue

            # For nested resources, join all path parts to create compound prefix
            # This matches how drf-spectacular generates operation_ids
            prefix = path_parts[-1]

            # Store mapping: operation_id prefix -> (ViewSet class name, path_parts_count)
            # Handle both simple and nested resources
            # Main resources (fewer path parts) get the simple prefix
            # Nested resources (more path parts) get compound prefixes
            path_parts_count = len(path_parts)

            if prefix not in OPERATION_CLASS_MAP:
                # First time seeing this prefix - store it with path count
                OPERATION_CLASS_MAP[prefix] = (class_name, path_parts_count)
            else:
                existing_class, existing_count = OPERATION_CLASS_MAP[prefix]

                if existing_class != class_name:
                    # Collision: different ViewSet for same prefix
                    # The ViewSet with FEWER path parts should own the simple prefix
                    if path_parts_count < existing_count:
                        # Current ViewSet is the main resource - it gets the simple prefix
                        # Move existing ViewSet to compound prefix
                        compound_prefix = '_'.join(path_parts[-2:]) if len(path_parts) >= 2 else prefix
                        OPERATION_CLASS_MAP[compound_prefix] = (existing_class, existing_count)
                        OPERATION_CLASS_MAP[prefix] = (class_name, path_parts_count)
                        logger.debug(f"Resource collision: {class_name} (main, {path_parts_count} parts) owns '{prefix}', {existing_class} moved to '{compound_prefix}'")
                    else:
                        # Existing ViewSet is the main resource - current one gets compound prefix
                        compound_prefix = '_'.join(path_parts[-2:]) if len(path_parts) >= 2 else prefix
                        OPERATION_CLASS_MAP[compound_prefix] = (class_name, path_parts_count)
                        logger.debug(f"Resource collision: {existing_class} (main, {existing_count} parts) keeps '{prefix}', {class_name} stored at '{compound_prefix}'")

            # Check if view has skip_ai_description attribute
            if getattr(view_class, 'skip_ai_description', False):
                SKIP_AI_DESCRIPTION_PREFIXES.add(prefix)
                logger.info(f"View class {class_name} (prefix: {prefix}) has skip_ai_description=True")

            # Check if view has resource_purpose attribute
            # Store by class name to avoid collisions between different ViewSets
            resource_purpose = getattr(view_class, 'resource_purpose', None)
            if resource_purpose:
                RESOURCE_PURPOSE_MAP[class_name] = resource_purpose
                logger.debug(f"View class {class_name} (prefix: {prefix}) has resource_purpose: {resource_purpose[:50]}...")

        except Exception as e:
            logger.debug(f"Error checking view metadata for {path} {method}: {e}")
            continue

    return endpoints
