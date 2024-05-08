import uuid
from functools import lru_cache
from typing import Union

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from .service_identifier import service_id


@lru_cache(maxsize=None)
def resource_type_cache(content_type_id):
    return ContentType.objects.get_for_id(content_type_id).resource_type


class ResourceType(models.Model):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ansible_base.resource_registry.registry import get_registry

        self.resource_registry = get_registry()

    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name="resource_type", unique=True)
    externally_managed = models.BooleanField()
    name = models.CharField(max_length=256, unique=True, db_index=True, editable=False, blank=False, null=False)

    @property
    def serializer_class(self):
        return self.get_resource_config().managed_serializer

    @property
    def can_be_managed(self):
        return self.externally_managed and self.serializer_class

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=ContentType.objects.get_for_id(self.content_type_id).model_class())


class Resource(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="resources")

    # this has to accommodate integer and UUID object IDs
    object_id = models.TextField(null=False, db_index=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    service_id = models.UUIDField(null=False, default=service_id)

    # we're not using this as the primary key because the ansible_id can change if the object is
    # externally managed.
    ansible_id = models.UUIDField(default=uuid.uuid4, db_index=True, unique=True)

    # human readable name for the resource
    name = models.CharField(max_length=512, null=True)

    def summary_fields(self):
        return {"ansible_id": self.ansible_id, "resource_type": self.resource_type}

    def __str__(self):
        return f'Resource(name={self.name}, object_id={self.object_id}, ansible_id={self.ansible_id})'

    @property
    def resource_type(self):
        return resource_type_cache(self.content_type.pk).name

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
    def get_resource_for_object(cls, obj):
        """
        Get the Resource instances for another model instance.
        """
        return cls.objects.get(object_id=obj.pk, content_type=ContentType.objects.get_for_model(obj).pk)

    def delete_resource(self):
        if not self.content_type.resource_type.can_be_managed:
            raise ValidationError({"resource_type": _(f"Resource type: {self.content_type.resource_type.name} cannot be managed by Resources.")})

        with transaction.atomic():
            self.content_object.delete()
            self.delete()

    @classmethod
    def create_resource(
        cls, resource_type: ResourceType, resource_data: dict, ansible_id: Union[str, uuid.UUID, None] = None, service_id: Union[str, uuid.UUID, None] = None
    ):
        c_type = resource_type.content_type
        serializer = resource_type.serializer_class(data=resource_data)
        serializer.is_valid(raise_exception=True)
        resource_data = serializer.validated_data
        processor = serializer.get_processor()

        with transaction.atomic():
            ObjModel = c_type.model_class()
            content_object = processor(ObjModel()).save(resource_data, is_new=True)
            resource = cls.objects.get(object_id=content_object.pk, content_type=c_type)

            if ansible_id:
                resource.ansible_id = ansible_id
            if service_id:
                resource.service_id = service_id
            resource.save()

            return resource

    def update_resource(self, resource_data: dict, ansible_id=None, partial=False, service_id: Union[str, uuid.UUID, None] = None):
        resource_type = self.content_type.resource_type

        serializer = resource_type.serializer_class(data=resource_data, partial=partial)
        serializer.is_valid(raise_exception=True)
        resource_data = serializer.validated_data

        processor = serializer.get_processor()

        with transaction.atomic():
            if ansible_id:
                self.ansible_id = ansible_id
            if service_id:
                self.service_id = service_id
            self.save()

            processor(self.content_object).save(resource_data)


# This is a separate function so that it can work with models from apps in the
# post migration signal.
def init_resource_from_object(obj, resource_model=None, resource_type=None, resource_config=None):
    """
    Initialize a new Resource object from another model instance.
    """
    if resource_type is None:
        c_type = ContentType.objects.get_for_model(obj)
        resource_type = c_type.resource_type
        assert resource_type is not None

    if resource_config is None:
        resource_config = resource_type.get_resource_config()

    if resource_model is None:
        resource_model = Resource

    resource = resource_model(object_id=obj.pk, content_type=resource_type.content_type)
    if hasattr(obj, resource_config.name_field):
        resource.name = str(getattr(obj, resource_config.name_field))[:512]

    return resource
