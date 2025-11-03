import logging

logger = logging.getLogger('ansible_base.api_documentation.preprocessing_hooks')

# Global storage for skip_ai_description operation ID prefixes
# Maps operation_id prefix (e.g. "teams") -> True for views with skip_ai_description
# This is shared with postprocessing_hooks.py
SKIP_AI_DESCRIPTION_PREFIXES = set()


def mark_skip_ai_description(endpoints, **kwargs):
    """
    Preprocessing hook that identifies views with skip_ai_description = True.

    This stores operation ID prefixes globally so the postprocessing hook
    can check them when generating x-ai-description fields.

    Preprocessing hooks receive: endpoints list
    """
    global SKIP_AI_DESCRIPTION_PREFIXES
    SKIP_AI_DESCRIPTION_PREFIXES.clear()

    if not endpoints:
        return endpoints

    for path, path_regex, method, view in endpoints:
        try:
            if hasattr(view, 'cls'):
                view_class = view.cls
            else:
                view_class = view.__class__

            # Check if view has skip_ai_description attribute
            if getattr(view_class, 'skip_ai_description', False):
                # Extract the resource prefix from the path
                # e.g., /api/gateway/v1/teams/ -> teams
                path_parts = [p for p in path.split('/') if p and not p.startswith('{')]
                if path_parts:
                    prefix = path_parts[-1]
                    SKIP_AI_DESCRIPTION_PREFIXES.add(prefix)
                    logger.info(f"View class {view_class.__name__} (prefix: {prefix}) has skip_ai_description=True")
        except Exception as e:
            logger.debug(f"Error checking skip_ai_description for {path} {method}: {e}")
            continue

    return endpoints
