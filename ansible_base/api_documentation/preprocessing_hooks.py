import logging
from typing import Any, Optional

from ansible_base.lib.utils.api_path_utils import parse_path_segments

logger = logging.getLogger('ansible_base.api_documentation.preprocessing_hooks')

# Spec generation is single-threaded, so the following globals should be safe

# Global storage for skip_ai_description operation ID prefixes
# Maps operation_id prefix (e.g. "teams") -> True for views with skip_ai_description
# This is shared with postprocessing_hooks.py
SKIP_AI_DESCRIPTION_PREFIXES = set()

# Global storage for resource_purpose values
# Maps ViewSet class name -> resource_purpose string
# This is shared with postprocessing_hooks.py
RESOURCE_PURPOSE_MAP = {}

# Global storage for ViewSet class names by operation_id prefix
# Maps operation_id prefix (e.g. "authenticators") -> (ViewSet class name, path_parts_count, path_parts)
# This is shared with postprocessing_hooks.py
# We store the count to resolve collisions: fewer path parts = main resource, gets simple prefix
# We store path_parts to generate correct compound prefixes when resolving collisions
OPERATION_CLASS_MAP = {}


def _get_view_class(view: Any) -> type:
    """Extract the ViewSet class from a view, handling DRF's view wrapping."""
    return getattr(view, 'cls', view.__class__)


def _extract_prefix_from_path(path: str) -> tuple[Optional[str], Optional[list[str]], Optional[int]]:
    """Extract the operation_id prefix from a URL path."""
    path_parts = parse_path_segments(path)
    if not path_parts:
        return None, None, None

    prefix = path_parts[-1]
    path_parts_count = len(path_parts)
    return prefix, path_parts, path_parts_count


def _create_compound_prefix(path_parts: list[str], fallback_prefix: str) -> str:
    """Create compound prefix from path parts (e.g., 'orgs_teams') to resolve collisions."""
    if len(path_parts) >= 2:
        return '_'.join(path_parts[-2:])
    return fallback_prefix


def _handle_prefix_collision(
    prefix: str, class_name: str, path_parts_count: int, path_parts: list[str], operation_class_map: dict[str, tuple[str, int, list[str]]]
) -> str:
    """
    Handle collision when multiple ViewSets use the same operation_id prefix.
    ViewSet with fewer path parts gets simple prefix; the other gets compound prefix.
    """
    existing_class, existing_count, existing_path_parts = operation_class_map[prefix]

    # Same ViewSet class - no collision
    if existing_class == class_name:
        return prefix

    # Different ViewSet - resolve collision
    if path_parts_count < existing_count:
        # Current is main resource - move existing to compound prefix
        # Use the existing entry's path_parts to create the correct compound prefix
        compound_prefix = _create_compound_prefix(existing_path_parts, prefix)
        operation_class_map[compound_prefix] = (existing_class, existing_count, existing_path_parts)
        operation_class_map[prefix] = (class_name, path_parts_count, path_parts)
        logger.debug(f"Resource collision: {class_name} (main, {path_parts_count} parts) owns '{prefix}', {existing_class} moved to '{compound_prefix}'")
        return prefix
    else:
        # Existing is main resource - current gets compound prefix
        compound_prefix = _create_compound_prefix(path_parts, prefix)
        operation_class_map[compound_prefix] = (class_name, path_parts_count, path_parts)
        logger.debug(f"Resource collision: {existing_class} (main, {existing_count} parts) keeps '{prefix}', {class_name} stored at '{compound_prefix}'")
        return compound_prefix


def _register_skip_ai_description(view_class: type, class_name: str, prefix: str) -> None:
    """Register a ViewSet that should skip AI description generation."""
    if getattr(view_class, 'skip_ai_description', False):
        SKIP_AI_DESCRIPTION_PREFIXES.add(prefix)
        logger.info(f"View class {class_name} (prefix: {prefix}) has skip_ai_description=True")


def _register_resource_purpose(view_class: type, class_name: str, prefix: str) -> None:
    """Register a ViewSet's resource_purpose for description generation."""
    resource_purpose = getattr(view_class, 'resource_purpose', None)
    if resource_purpose:
        RESOURCE_PURPOSE_MAP[class_name] = resource_purpose
        logger.debug(f"View class {class_name} (prefix: {prefix}) has resource_purpose: {resource_purpose[:50]}{'...' if len(resource_purpose) > 50 else ''}")


def collect_ai_description_metadata(endpoints: Optional[list[tuple[str, str, str, Any]]], **kwargs) -> Optional[list[tuple[str, str, str, Any]]]:
    """
    Preprocessing hook for drf-spectacular that collects metadata from ViewSets for AI description generation.

    This hook runs before OpenAPI schema generation and inspects all registered ViewSets/APIViews
    to collect metadata that will be used by the postprocessing hook to generate x-ai-description fields.

    The hook collects three types of metadata:
    1. skip_ai_description flags - ViewSets that have opted out of AI description generation
    2. resource_purpose values - Custom purpose strings for template-based description generation
    3. Operation ID mappings - Relationships between operation prefixes and ViewSet classes

    When multiple ViewSets share the same operation prefix (e.g., nested resources), the hook
    automatically resolves naming collisions by giving the ViewSet with fewer path parts the
    simple prefix, and assigning compound prefixes to nested resources.

    The collected metadata is stored in global variables (SKIP_AI_DESCRIPTION_PREFIXES,
    RESOURCE_PURPOSE_MAP, OPERATION_CLASS_MAP) that are shared with the postprocessing hook.

    Args:
        endpoints: List of endpoint tuples (path, path_regex, method, view)
        **kwargs: Additional keyword arguments (unused)

    Returns:
        The unmodified endpoints list

    Side effects:
        - Clears and repopulates SKIP_AI_DESCRIPTION_PREFIXES set
        - Clears and repopulates RESOURCE_PURPOSE_MAP dict
        - Clears and repopulates OPERATION_CLASS_MAP dict
    """
    global SKIP_AI_DESCRIPTION_PREFIXES, RESOURCE_PURPOSE_MAP, OPERATION_CLASS_MAP
    SKIP_AI_DESCRIPTION_PREFIXES.clear()
    RESOURCE_PURPOSE_MAP.clear()
    OPERATION_CLASS_MAP.clear()

    if endpoints:
        for path, path_regex, method, view in endpoints:
            try:
                # Extract ViewSet class from the view
                view_class = _get_view_class(view)
                class_name = view_class.__name__

                # Extract operation_id prefix from path
                prefix, path_parts, path_parts_count = _extract_prefix_from_path(path)
                if prefix is None:
                    continue

                # Store or handle collision for this prefix
                if prefix not in OPERATION_CLASS_MAP:
                    # First time seeing this prefix - store it
                    OPERATION_CLASS_MAP[prefix] = (class_name, path_parts_count, path_parts)
                else:
                    # Handle collision (different ViewSet with same prefix)
                    prefix = _handle_prefix_collision(prefix, class_name, path_parts_count, path_parts, OPERATION_CLASS_MAP)

                # Register ViewSet attributes for AI description generation
                _register_skip_ai_description(view_class, class_name, prefix)
                _register_resource_purpose(view_class, class_name, prefix)

            except Exception as e:
                logger.debug(f"Error checking view metadata for {path} {method}: {e}")
                continue

    return endpoints
