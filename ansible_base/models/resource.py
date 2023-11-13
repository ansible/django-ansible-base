from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid

_resource_registry = None


# Circular imports make this really hard to initialize correctly.
def get_registry():
    global _resource_registry
    if _resource_registry is None:
        from django.conf import settings

        if settings.RESOURCE_REGISTRY_CONFIG:
            from django.utils.module_loading import import_string

            _resource_registry = import_string(settings.RESOURCE_REGISTRY_CONFIG)
        else:
            from ansible_base.utils.resource_registry import ResourceRegistry

            _resource_registry = ResourceRegistry()
    return _resource_registry


class ResourceType(models.Model):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resource_registry = get_registry()

    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name="resource_type", unique=True)
    externally_managed = models.BooleanField()

    @property
    def parent_types(self):
        return list(self.resource_registry.get_parents(self.resource_type))

    @property
    def child_types(self):
        return self.get_resource_config()["child_resources"].keys()

    @property
    def resource_type(self):
        return self.content_type.model_class()._meta.label

    def get_all_child_types(self):
        return self.resource_registry.get_all_children(self.resource_type)

    def get_resource_config(self):
        return self.resource_registry.get_config_for_model(model=self.content_type.model_class())

    @classmethod
    def update_resource_types_from_registry(cls):
        for key, resource in get_registry().get_resources().items():
            content = ContentType.objects.get_for_model(resource["model"])
            cls.objects.update_or_create(content_type=content, externally_managed=resource["externally_managed"])


class Resource(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="resources")
    object_id = models.PositiveIntegerField(null=True, default=None)
    content_object = GenericForeignKey('content_type', 'object_id')

    # we're not using this as the primary key because the ansible_id can change if the object is
    # externally managed.
    ansible_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    resource_hash = models.CharField(max_length=512, null=True)

    class Meta:
        unique_together = ('content_type', 'object_id')

    # TODO: this is PAINFULLY inefficient
    # not sure if it's better to compute this information on the fly or to pre compute it
    # with a many to many field.
    def get_parents(self):
        registry = get_registry()
        model = self.content_type.model_class()
        parent_types = registry.get_parents(model_label=model._meta.label)

        #
        if len(parent_types) == 0 or self.content_object is None:
            return Resource.objects.none()

        query = models.Q()

        for p in parent_types:
            parent_config = registry.get_config_for_model(model_label=p)
            field_name = parent_config["child_resources"][model._meta.label]["child_field_name"]
            parent_id = getattr(self.content_object, field_name).pk

            query = query | models.Q(object_id=parent_id, content_type=ContentType.objects.get_for_model(parent_config["model"]))

        return Resource.objects.filter(query)

    @classmethod
    def update_index(cls):
        for r in ResourceType.objects.all():
            resource_model = r.content_type.model_class()

            data = []
            for obj in resource_model.objects.all():
                data.append(cls(content_object=obj))

            cls.objects.bulk_create(data, ignore_conflicts=True)


# TODO: rename this to something that doesn't conflict with django permissions
class Permission(models.Model):
    resource_type = models.ForeignKey(ResourceType, null=False, on_delete=models.CASCADE, related_name="resource_permission")
    action = models.CharField(max_length=32)

    class Meta:
        unique_together = ('resource_type', 'action')

    @classmethod
    def update_permissions(cls):
        for r in ResourceType.objects.all():
            data = []
            if actions := r.get_resource_config().get("actions"):
                for action in actions:
                    data.append(cls(resource_type=r, action=action))

            cls.objects.bulk_create(data, ignore_conflicts=True)


# class RoleType(models.Model):
#     pass


# class UserRole(models.Model):
#     pass


# class TeamRole(models.Model):
#     pass
