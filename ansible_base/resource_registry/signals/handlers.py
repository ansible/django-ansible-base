from functools import lru_cache

from ansible_base.resource_registry.models import Resource, init_resource_from_object
from ansible_base.resource_registry.registry import get_concrete_model, get_registry


@lru_cache(maxsize=1)
def get_resource_models():
    resource_models = set()
    registry = get_registry()
    if registry:
        for k, resource in registry.get_resources().items():
            resource_models.add(resource.model)

    return resource_models


# @receiver(post_delete)
def remove_resource(sender, instance, **kwargs):
    model = get_concrete_model(sender)
    if model in get_resource_models():
        try:
            resource = Resource.get_resource_for_object(instance)
            resource.delete()
        except Resource.DoesNotExist:
            return


# @receiver(post_save)
def update_resource(sender, instance, created, **kwargs):
    model = get_concrete_model(sender)
    if model in get_resource_models():
        if created:
            resource = init_resource_from_object(instance)
            resource.save()
        else:
            resource = Resource.get_resource_for_object(instance)
            resource.update_from_content_object()
