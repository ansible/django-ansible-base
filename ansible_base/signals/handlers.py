from functools import lru_cache

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ansible_base.models import Resource
from ansible_base.models.resource import get_registry
from ansible_base.resource_registry.registry import get_concrete_model
from ansible_base.utils.transactions import create_transaction

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
    if sender._meta.object_name == 'Migration':
        return
    model = get_concrete_model(sender)
    if model in get_resource_models():
        Resource.objects.filter(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance).pk).delete()


@receiver(post_save)
def update_resource(sender, instance, created, **kwargs):
    if sender._meta.object_name == 'Migration':
        return
    model = get_concrete_model(sender)
    if model in get_resource_models():
        name = None
        resource_config = get_registry().get_config_for_model(model=model)
        if hasattr(instance, resource_config["name_field"]):
            name = getattr(instance, resource_config["name_field"])
        if created:
            Resource.objects.update_or_create(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance), defaults={"name": name})
        elif name:
            Resource.objects.filter(object_id=instance.pk, content_type=ContentType.objects.get_for_model(instance)).update(name=name)
