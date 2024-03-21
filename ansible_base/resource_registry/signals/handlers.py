from functools import lru_cache

from ansible_base.resource_registry.models import Resource, init_resource_from_object
from ansible_base.resource_registry.registry import get_registry


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
    if created:
        resource = init_resource_from_object(instance)
        resource.save()
    else:
        resource = Resource.get_resource_for_object(instance)
        resource.update_from_content_object()
