import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .service_id import service_id


def short_service_id():
    return service_id().split('-')[0]


class ResourceType(models.Model):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ansible_base.resource_registry.registry import get_registry

        self.resource_registry = get_registry()

    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name="resource_type", unique=True)
    externally_managed = models.BooleanField()
    migrated = models.BooleanField(null=False, default=False)
    name = models.CharField(max_length=256, unique=True, db_index=True, editable=False, blank=False, null=False)

    @property
    def serializer_class(self):
        return self.get_resource_config().managed_serializer

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=self.content_type.model_class())


class Resource(models.Model):
    # objects = ResourceManager()

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="resources")

    # this has to accommodate integer and UUID object IDs
    object_id = models.TextField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')

    service_id = models.CharField(default=short_service_id, max_length=8)

    # we're not using this as the primary key because the ansible_id can change if the object is
    # externally managed.
    resource_id = models.UUIDField(default=uuid.uuid4, db_index=True, unique=True)

    # human readable name for the resource
    name = models.CharField(max_length=512, null=True)

    @property
    def ansible_id(self):
        return self.service_id + ":" + str(self.resource_id)

    @ansible_id.setter
    def ansible_id(self, val):
        s_id, r_id = val.split(":")
        if not service_id().startswith(s_id):
            self.service_id = s_id

        self.resource_id = r_id

    @property
    def resource_type(self):
        return self.content_type.resource_type.name

    class Meta:
        unique_together = ('content_type', 'object_id')
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def update_from_content_object(self):
        """
        Update any cached attributes from the Resource's content_object
        """
        name_field = self.content_type.resource_type.get_resource_config().name_field

        if hasattr(self.content_object, name_field):
            name = getattr(self.content_object, name_field)[:512]
            if self.name != name:
                self.name = name
                self.save()

    @classmethod
    def init_from_object(cls, obj, resource_type=None):
        """
        Initialize a new Resource object from another model instance.
        """
        if resource_type is None:
            c_type = ContentType.objects.get_for_model(obj)
            resource_type = c_type.resource_type
            assert resource_type is not None

        resource = cls(object_id=obj.pk, content_type=resource_type.content_type)
        resource_config = resource_type.get_resource_config()
        if hasattr(obj, resource_config.name_field):
            resource.name = str(getattr(obj, resource_config.name_field))[:512]

        return resource

    @classmethod
    def get_resource_for_object(cls, obj):
        """
        Get the Resource instances for another model instance.
        """
        return cls.objects.get(object_id=obj.pk, content_type=ContentType.objects.get_for_model(obj).pk)
