from functools import lru_cache

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ansible_base.models import Resource
from ansible_base.models.resource import get_registry


@lru_cache(maxsize=1)
def get_resource_models():
    resource_models = set()
    registry = get_registry()
    if registry:
        for k, resource in registry.get_resources().items():
            resource_models.add(resource["model"])

    return resource_models


@receiver(post_delete)
def remove_resource(sender, instance, **kwargs):
    if sender in get_resource_models():
        Resource.objects.filter(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance).pk).delete()


@receiver(post_save)
def update_resource(sender, instance, created, **kwargs):
    if sender in get_resource_models():
        name = None
        if hasattr(instance, "name"):
            name = instance.name
        if created:
            Resource.objects.update_or_create(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance), defaults={"name": name})
        elif name:
            Resource.objects.filter(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance)).update(name=instance.name)
