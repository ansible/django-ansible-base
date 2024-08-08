import logging
from typing import Optional

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource, ResourceType

logger = logging.getLogger('ansible_base.serializers')


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


class ResourceListSerializer(serializers.ModelSerializer):
    has_serializer = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    resource_type = serializers.CharField(required=False)
    resource_data = ResourceDataField(source="*", write_only=True)

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
            "is_partially_migrated",
            "resource_type",
            "has_serializer",
            "resource_data",
            "url",
        ]

    def get_url(self, obj) -> str:
        # conversion to string is done to satisfy type checking and OpenAPI schema generator
        return get_relative_url('resource-detail', kwargs={"ansible_id": obj.ansible_id})

    def get_has_serializer(self, obj) -> bool:
        return bool(obj.content_type.resource_type.get_resource_config().managed_serializer)

    # update ansible ID
    def update(self, instance, validated_data):
        resource_type = instance.content_type.resource_type
        if not resource_type.can_be_managed:
            raise serializers.ValidationError({"resource_type": _(f"Resource type: {resource_type.name} cannot be managed by Resources.")})

        instance.update_resource(
            validated_data.get("resource_data", {}),
            ansible_id=validated_data.get("ansible_id"),
            is_partially_migrated=validated_data.get("is_partially_migrated"),
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


class ResourceSerializer(ResourceListSerializer):
    additional_data = serializers.SerializerMethodField()
    resource_data = ResourceDataField(source="*")

    class Meta:
        model = ResourceListSerializer.Meta.model
        read_only_fields = ResourceListSerializer.Meta.read_only_fields
        fields = ResourceListSerializer.Meta.fields + [
            "additional_data",
        ]

    def get_additional_data(self, obj):
        if serializer := obj.content_type.resource_type.serializer_class:
            if serializer.ADDITIONAL_DATA_SERIALIZER is not None:
                return serializer.ADDITIONAL_DATA_SERIALIZER(obj.content_object).data

        return None


class ResourceTypeSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "name", "externally_managed", "shared_resource_type", "url"]

    def get_shared_resource_type(self, obj) -> Optional[str]:
        if serializer := obj.get_resource_config().managed_serializer:
            return serializer.RESOURCE_TYPE
        else:
            return None

    def get_url(self, obj) -> str:
        return get_relative_url('resourcetype-detail', kwargs={"name": obj.name})


class UserAuthenticationSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
