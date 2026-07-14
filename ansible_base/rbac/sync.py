"""
Module is a parallel to resource_registry

ansible_base.resource_registry.utils.sync_to_resource_server.sync_to_resource_server

This module handles RBAC-specific reverse-sync scenarios:
1. Role assignments - which have key differences:
   - totally immutable model
   - have very weird way of referencing related objects
   - must run various internal RBAC logic for rebuilding RoleEvaluation entries
2. RoleDefinition sync timing - which has timing issues:
   - post_save fires before many-to-many relations are saved
   - permissions need to be attached before syncing
3. Object deletion cleanup - cross-service sync for orphaned assignments
"""

import logging

logger = logging.getLogger('ansible_base.rbac.sync')


def reverse_sync_enabled_all_conditions(instance):
    """This checks for basically all cases we do not reverse sync
    1. global reverse sync enabled flag (including context manager)
    2. RESOURCE_SERVER setting not actually set
    3. environment variable to skip sync
    4. object level flag for skipping the sync
    """
    from ansible_base.resource_registry.apps import _should_reverse_sync
    from ansible_base.resource_registry.signals.handlers import reverse_sync_enabled
    from ansible_base.resource_registry.utils.sync_to_resource_server import should_skip_reverse_sync

    if not reverse_sync_enabled.enabled:
        return False

    if not _should_reverse_sync():
        return False

    if should_skip_reverse_sync(instance):
        return False

    return True


def maybe_reverse_sync_assignment(assignment):
    if not reverse_sync_enabled_all_conditions(assignment):
        return

    from ansible_base.resource_registry.utils.sync_to_resource_server import get_current_user_resource_client

    client = get_current_user_resource_client()
    client.sync_assignment(assignment)


def maybe_reverse_sync_unassignment(role_definition, actor, content_object):
    if not reverse_sync_enabled_all_conditions(role_definition):
        return

    from ansible_base.resource_registry.utils.sync_to_resource_server import get_current_user_resource_client

    client = get_current_user_resource_client()
    client.sync_unassignment(role_definition, actor, content_object)


def reverse_sync_enabled_global():
    """Check global reverse-sync conditions that do not depend on a specific instance.

    This checks:
    1. global reverse sync enabled flag (including context manager)
    2. RESOURCE_SERVER setting
    Does NOT check instance-level skip flags or environment variable overrides
    since those are per-instance and not relevant for batch operations.
    """
    from ansible_base.resource_registry.apps import _should_reverse_sync
    from ansible_base.resource_registry.signals.handlers import reverse_sync_enabled

    if not reverse_sync_enabled.enabled:
        return False

    if not _should_reverse_sync():
        return False

    return True


def maybe_reverse_sync_object_deletions_batch(deleted_objects):
    """Trigger batch reverse-sync for multiple object deletions.

    Args:
        deleted_objects: list of (app_label, model, pk_string) tuples
    """
    if not deleted_objects:
        return

    if not reverse_sync_enabled_global():
        logger.debug("Skipping batch reverse-sync object deletion (%d objects)", len(deleted_objects))
        return

    import os

    sync_disabled = os.environ.get('ANSIBLE_REVERSE_RESOURCE_SYNC', 'true').lower() == 'false'
    if sync_disabled:
        logger.warning("Skipping batch reverse-sync object deletion because $ANSIBLE_REVERSE_RESOURCE_SYNC is 'false'")
        return

    logger.debug("Performing batch reverse-sync object deletion for %d objects", len(deleted_objects))

    try:
        from ansible_base.resource_registry.utils.sync_to_resource_server import get_current_user_resource_client

        client = get_current_user_resource_client()
        result = client.sync_object_deletions_batch(deleted_objects)
        if isinstance(result, dict) and result.get('error'):
            logger.warning("Batch reverse-sync of %d object deletions failed: %s", len(deleted_objects), result.get('error'))
        else:
            actual_deleted = result.get('deleted_count', 0) if isinstance(result, dict) else 0
            logger.debug("Batch synced object deletions: sent %d, server deleted %d assignments", len(deleted_objects), actual_deleted)
    except Exception:
        logger.exception("Failed to batch sync %d object deletions", len(deleted_objects))


def maybe_reverse_sync_object_deletion(content_object):
    """Trigger reverse-sync for object deletion to clean up orphaned role assignments.
    This is called when a resource with object-level role assignments is deleted.

    Args:
        content_object: The deleted resource instance to clean up assignments for
    """
    if not reverse_sync_enabled_all_conditions(content_object):
        logger.debug(f"Skipping reverse-sync object deletion for {content_object}")
        return

    logger.debug(f"Performing reverse-sync object deletion for {content_object}")

    try:
        from ansible_base.resource_registry.utils.sync_to_resource_server import get_current_user_resource_client

        client = get_current_user_resource_client()
        client.sync_object_deletion(content_object)
        logger.debug(f"Successfully synced object deletion for {content_object}")
    except Exception as e:
        # Log the error but don't let sync failures break local deletion
        logger.warning(f"Failed to sync object deletion for {content_object}: {e}")
        return


def maybe_reverse_sync_role_definition(instance, action="update"):
    """Manually trigger reverse-sync for a RoleDefinition if appropriate.

    This should be called after the instance is fully constructed with
    all many-to-many relationships saved.

    Args:
        instance: The RoleDefinition instance to sync
        action: The action type ("create" or "update")
    """
    if not reverse_sync_enabled_all_conditions(instance):
        logger.debug(f"Skipping reverse-sync for {instance} (action: {action})")
        return

    logger.debug(f"Performing reverse-sync for {instance} (action: {action})")

    # Use the same logic as the post_save signal handler
    from ansible_base.resource_registry.signals.handlers import sync_to_resource_server_post_save

    created = action == "create"
    sync_to_resource_server_post_save(sender=type(instance), instance=instance, created=created, update_fields=None)
