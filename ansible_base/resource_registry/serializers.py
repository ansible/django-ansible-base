import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.reverse import reverse_lazy

from ansible_base.resource_registry.models import Resource, ResourceType

logger = logging.getLogger('ansible_base.serializers')


def get_resource_detail_view(resource: Resource):
    # TODO: format this so that it uses the correct API base path for the proxy.
    actions = resource.content_type.resource_type.get_resource_config().actions

    # TODO: this needs some more logic to handle cases where the detail view isn't
    # name or pk, and in cases where there may be multiple detail views (such as with
    # nested API views). This may be solvable by providing a reverse_url_name when
    # resources are registered.
    if detail := actions.get("retrieve"):
        # Try the shortest URL first because it is most likely to be the detail and correct view
        resource_pk_field = resource.content_type.resource_type.get_resource_config().model._meta.pk.name
        format_data = {"pk": resource.object_id, "name": resource.name, resource_pk_field: resource.object_id}
        for http_method, url_template in sorted(detail, key=lambda item: len(item[-1])):
            try:
                return url_template.format(**format_data)
            except KeyError:
                pass
        logger.warning(f'Failed to obtain resource URL from options {detail}')

    return None


class ResourceDataField(serializers.JSONField):
    """
    Inspects the content object. If it has a managed serializer,
    serialize the data using it.
    """

    def to_representation(self, resource):
        if serializer := resource.content_type.resource_type.serializer_class:
            return serializer(resource.content_object).data
        return {}

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        return {self.field_name: data}


class ResourceSerializer(serializers.ModelSerializer):
    has_serializer = serializers.SerializerMethodField()
    resource_data = ResourceDataField(source="*")
    detail_url = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    resource_type = serializers.CharField(required=False)

    class Meta:
        model = Resource
        read_only_fields = [
            "object_id",
            "name",
        ]
        fields = [
            "object_id",
            "name",
            "ansible_id",
            "service_id",
            "resource_type",
            "has_serializer",
            "resource_data",
            "detail_url",
            "url",
        ]

    def get_url(self, obj):
        return reverse_lazy('resource-detail', kwargs={"ansible_id": obj.ansible_id})

    def get_detail_url(self, obj):
        return get_resource_detail_view(obj)

    def get_has_serializer(self, obj):
        return bool(obj.content_type.resource_type.get_resource_config().managed_serializer)

    # update ansible ID
    def update(self, instance, validated_data):
        resource_type = instance.content_type.resource_type
        if not resource_type.can_be_managed:
            raise serializers.ValidationError({"resource_type": _(f"Resource type: {resource_type.name} cannot be managed by Resources.")})

        instance.update_resource(
            validated_data.get("resource_data", {}),
            ansible_id=validated_data.get("ansible_id"),
            service_id=validated_data.get("service_id"),
            partial=self.partial,
        )
        instance.refresh_from_db()
        return instance

    # allow setting ansible ID at create time
    def create(self, validated_data):
        try:
            if not validated_data["resource_type"]:
                raise serializers.ValidationError({"resource_type": _("This field is required for resource creation.")})

            resource_type = ResourceType.objects.get(name=validated_data["resource_type"])
            if not resource_type.can_be_managed:
                raise serializers.ValidationError({"resource_type": _(f"Resource type: {resource_type.name} cannot be managed by Resources.")})

            return Resource.create_resource(
                resource_type, validated_data["resource_data"], ansible_id=validated_data.get("ansible_id"), service_id=validated_data.get("service_id")
            )

        except ResourceType.DoesNotExist:
            raise serializers.ValidationError({"resource_type": _(f"Resource type: {validated_data['resource_type']} does not exist.")})


class ResourceListSerializer(ResourceSerializer):
    resource_data = ResourceDataField(source="*", write_only=True)


class ResourceTypeSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "name", "externally_managed", "shared_resource_type", "url"]

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().managed_serializer:
            return serializer.RESOURCE_TYPE
        else:
            return None

    def get_url(self, obj):
        return reverse_lazy('resourcetype-detail', kwargs={"name": obj.name})
