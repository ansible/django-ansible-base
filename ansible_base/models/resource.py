import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.functions import Concat
from django.db.utils import ProgrammingError

from .service_id import service_id

_resource_registry = None


# Circular imports make this really hard to initialize correctly.
# I don't know why, but I can't put this function anywhere else without inducing
# circular imports.
def get_registry():
    global _resource_registry
    if _resource_registry is None:
        from django.conf import settings

        if hasattr(settings, "RESOURCE_REGISTRY_CONFIG"):
            from django.utils.module_loading import import_string

            _resource_registry = import_string(settings.RESOURCE_REGISTRY_CONFIG)
        else:
            _resource_registry = False
    return _resource_registry


class ResourceManager(models.Manager):
    """
    Ansible IDs are made up of two parts: the service short ID and a resource
    UUIDv4. For efficiency reasons, these are stored as two separate fields:
        - _service_id: Service that the resource belongs to.
        - resource_id: Resource UUID.

    Since Ansible ID is the value that will be referenced in the API, this
    manager automatically annotates ansible_id as <service_short_id>:<resource_id>
    for easier lookups.
    """

    def get_queryset(self):
        # this needs to wait for migrations to run before it becomes available.
        try:
            s_id = service_id().split('-')[0]
        except ProgrammingError:
            s_id = "00000000"

        return (
            super()
            .get_queryset()
            .annotate(
                _computed_service_id=models.Case(
                    models.When(_service_id__isnull=False, then=models.F('_service_id')), default=models.Value(s_id), output_field=models.CharField()
                ),
                _ansible_id=Concat("_computed_service_id", models.Value(":"), models.F("resource_id"), output_field=models.CharField()),
            )
        )


class ResourceType(models.Model):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resource_registry = get_registry()

    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name="resource_type", unique=True)
    externally_managed = models.BooleanField()
    migrated = models.BooleanField(null=False, default=False)
    name = models.CharField(max_length=256, unique=True, db_index=True, editable=False, blank=False, null=False)

    @property
    def serializer_class(self):
        return self.get_resource_config()["managed_serializer"]

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=self.content_type.model_class())


class Resource(models.Model):
    objects = ResourceManager()

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="resources")

    # this has to accommodate integer and UUID object IDs
    object_id = models.TextField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')

    _service_id = models.CharField(null=True, max_length=8)

    # we're not using this as the primary key because the ansible_id can change if the object is
    # externally managed.
    resource_id = models.UUIDField(default=uuid.uuid4, db_index=True, unique=True)

    # human readable name for the resource
    name = models.CharField(max_length=256, null=True)

    @property
    def service_id(self):
        return self._computed_service_id

    @property
    def ansible_id(self):
        return self._ansible_id

    @ansible_id.setter
    def ansible_id(self, val):
        s_id, r_id = val.split(":")
        if not service_id().startswith(s_id):
            self._service_id = s_id

        self.resource_id = r_id

    @property
    def type_name(self):
        return self.content_type.resource_type.type_name

    class Meta:
        unique_together = ('content_type', 'object_id')
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]
