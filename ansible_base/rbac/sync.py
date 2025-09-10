"""
Module is a parallel to resource_registry

ansible_base.resource_registry.utils.sync_to_resource_server.sync_to_resource_server

However, this only deals with role assignments, which have key differences
- totally immutable model
- have very weird way of referencing related objects
- must run various internal RBAC logic for rebuilding RoleEvaluation entries
"""


def reverse_sync_enabled_all_conditions(assignment):
    """This checks for basically all cases we do not reverse sync
    1. object level flag for skipping the sync
    2. environment variable to skip sync
    3. context manager to disable sync
    4. RESOURCE_SERVER setting not actually set
    """
    from ansible_base.resource_registry.apps import _should_reverse_sync
    from ansible_base.resource_registry.signals.handlers import reverse_sync_enabled
    from ansible_base.resource_registry.utils.sync_to_resource_server import should_skip_reverse_sync

    if not _should_reverse_sync():
        return False

    if not reverse_sync_enabled.enabled:
        return False

    if should_skip_reverse_sync(assignment):
        return

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
