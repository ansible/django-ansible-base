import threading
from contextlib import contextmanager
from functools import lru_cache

from ansible_base.resource_registry.models import Resource, init_resource_from_object
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.utils.sync_to_resource_server import sync_to_resource_server


@lru_cache(maxsize=1)
def get_resource_models():
    resource_models = set()
    registry = get_registry()
    if registry:
        for k, resource in registry.get_resources().items():
            resource_models.add(resource.model)

    return resource_models


def remove_resource(sender, instance, **kwargs):
    try:
        resource = Resource.get_resource_for_object(instance)
        resource.delete()
    except Resource.DoesNotExist:
        return


def update_resource(sender, instance, created, **kwargs):
    try:
        resource = Resource.get_resource_for_object(instance)
        resource.update_from_content_object()
    except Resource.DoesNotExist:
        resource = init_resource_from_object(instance)
        resource.save()


# pre_save
def decide_to_sync_update(sender, instance, raw, using, update_fields, **kwargs):
    """
    A pre_save hook that decides whether or not to reverse-sync the instance
    based on which fields have changed.

    This has to be in pre-save because we have to be able to get the original
    instance to calculate which fields changed, if update_fields wasn't passed
    """

    if instance._state.adding:
        # We only concern ourselves with updates
        return

    try:
        resource = Resource.get_resource_for_object(instance)
    except Resource.DoesNotExist:
        # We can't sync here, but we want to log that, so let sync_to_resource_server() discard it.
        return

    fields_that_sync = resource.content_type.resource_type.serializer_class().get_fields().keys()

    if update_fields is None:
        # If we're not given a useful update_fields, manually calculate the changed fields
        # at the cost of an extra query
        existing_instance = sender.objects.get(pk=instance.pk)
        changed_fields = set()
        for field in fields_that_sync:
            if getattr(existing_instance, field) != getattr(instance, field):
                changed_fields.add(field)
    else:
        # If we're given update_fields, we can just check those
        changed_fields = set(update_fields)

    if not changed_fields.intersection(fields_that_sync):
        instance._skip_reverse_resource_sync = True


class ReverseSyncEnabled(threading.local):
    def __init__(self):
        self.enabled = True

    def __bool__(self):
        return self.enabled


reverse_sync_enabled = ReverseSyncEnabled()


@contextmanager
def no_reverse_sync():
    previous_value = reverse_sync_enabled.enabled
    reverse_sync_enabled.enabled = False
    try:
        yield
    finally:
        reverse_sync_enabled.enabled = previous_value


# post_save
def sync_to_resource_server_post_save(sender, instance, created, update_fields, **kwargs):
    if not reverse_sync_enabled:
        return

    action = "create" if created else "update"
    sync_to_resource_server(instance, action)


# pre_delete
def sync_to_resource_server_pre_delete(sender, instance, **kwargs):
    if not reverse_sync_enabled:
        return

    sync_to_resource_server(instance, "delete", ansible_id=instance.resource.ansible_id)
