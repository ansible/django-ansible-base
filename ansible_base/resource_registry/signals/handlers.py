from functools import lru_cache

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.registry import get_concrete_model, get_registry


@lru_cache(maxsize=1)
def get_resource_models():
    resource_models = set()
    registry = get_registry()
    if registry:
        for k, resource in registry.get_resources().items():
            resource_models.add(resource.model)

    return resource_models


@receiver(post_delete)
def remove_resource(sender, instance, **kwargs):
    if sender._meta.object_name == 'Migration':
        return
    model = get_concrete_model(sender)
    if model in get_resource_models():
        resource = Resource.get_resource_for_object(instance)
        resource.delete()


@receiver(post_save)
def update_resource(sender, instance, created, **kwargs):
    if sender._meta.object_name == 'Migration':
        return
    model = get_concrete_model(sender)
    if model in get_resource_models():
        if created:
            resource = Resource.init_from_object(instance)
            resource.save()
        else:
            resource = Resource.get_resource_for_object(instance)
            resource.update_from_content_object()
