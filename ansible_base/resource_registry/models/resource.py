import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.lib.utils.hashing import hash_serializer_data

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

    @property
    def can_be_managed(self):
        return self.externally_managed and self.serializer_class

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=self.content_type.model_class())


class ResourceManager(models.Manager):
    """
    Call computation of resource_hash because bulk operations doesn't trigger 
    signals or customizations made on .save
    """
    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj.set_resource_hash()
        return super().bulk_create(objs, *args, **kwargs)
    
    def bulk_update(self, objs, *args, **kwargs):
        for obj in objs:
            obj.set_resource_hash()
        return super().bulk_update(objs, *args, **kwargs)


class Resource(models.Model):
    objects = ResourceManager()

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

    # Sha256 Hash hexdigest of the value on resource_data serialized by ResourceSerializer
    # This field is automatically computed on save, update and bulk_create
    resource_hash = models.CharField(max_length=64, db_index=True, null=True)

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

    def save(self, *args, **kwargs):
        self.set_resource_hash()
        return super().save(*args, **kwargs)

    def set_resource_hash(self):
        """
        Set resource hash based on ResourceSerializer data.
        # note: this doesn't save the object, so it can be called on bulk operations
        # and must be called before a .save()
        """
        # lazy import to avoid cyclic reference
        from ansible_base.resource_registry.serializers import ResourceSerializer
        resource_data = ResourceSerializer(self).data["resource_data"]
        self.resource_hash = hash_serializer_data(resource_data)

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
    def create_resource(cls, resource_type: ResourceType, resource_data: dict, ansible_id: str = None):
        if not resource_type.can_be_managed:
            raise ValidationError({"resource_type": _(f"Resource type: {resource_type.name} cannot be managed by Resources.")})
        c_type = resource_type.content_type
        serializer = resource_type.serializer_class(data=resource_data)
        serializer.is_valid(raise_exception=True)
        resource_data = serializer.validated_data

        with transaction.atomic():
            content_object = c_type.model_class().objects.create(**resource_data)
            content_object.save()

            resource = cls.objects.get(object_id=content_object.pk, content_type=c_type)

            if ansible_id:
                resource.ansible_id = ansible_id
                resource.save()

            return resource

    def update_resource(self, resource_data: dict, ansible_id=None, partial=False):
        resource_type = self.content_type.resource_type

        if not resource_type.can_be_managed:
            raise ValidationError({"resource_type": _(f"Resource type: {resource_type.name} cannot be managed by Resources.")})

        serializer = resource_type.serializer_class(data=resource_data, partial=partial)
        serializer.is_valid(raise_exception=True)
        resource_data = serializer.validated_data

        with transaction.atomic():
            for k, val in resource_data.items():
                setattr(self.content_object, k, val)
                self.content_object.save()

            if ansible_id:
                self.ansible_id = ansible_id
                self.save()


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
