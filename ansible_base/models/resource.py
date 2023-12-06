import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .service_id import service_id

_resource_registry = None


# Circular imports make this really hard to initialize correctly.
# I don't know why, but I can't put this function anywhere else without inducing
# circular imports.
def get_registry():
    global _resource_registry
    if _resource_registry is None:
        from django.conf import settings

        if settings.RESOURCE_REGISTRY_CONFIG:
            from django.utils.module_loading import import_string

            _resource_registry = import_string(settings.RESOURCE_REGISTRY_CONFIG)
        else:
            from ansible_base.resource_registry import ResourceRegistry

            _resource_registry = ResourceRegistry()
    return _resource_registry


class ResourceType(models.Model):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resource_registry = get_registry()

    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name="resource_type", unique=True)
    externally_managed = models.BooleanField()
    migrated = models.BooleanField(null=False, default=False)
    resource_type = models.CharField(max_length=256, unique=True, db_index=True)

    @property
    def serializer_class(self):
        return self.get_resource_config()["managed_serializer"]

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=self.content_type.model_class())


class Resource(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="resources")

    # this has to accommodate integer and UUID object IDs
    object_id = models.TextField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')

    _service_id = models.UUIDField(null=True)

    # we're not using this as the primary key because the ansible_id can change if the object is
    # externally managed.
    ansible_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    # human readable name for the resource
    name = models.CharField(max_length=256, null=True)

    @property
    def resource_type(self):
        return self.content_type.resource_type.resource_type

    class Meta:
        unique_together = ('content_type', 'object_id')
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    @property
    def service_id(self):
        if not self._service_id:
            return service_id()
        else:
            return self._service_id
