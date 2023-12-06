import logging

from rest_framework import serializers

from ansible_base.models import Resource, ResourceType

logger = logging.getLogger('ansible_base.serializers')


class ResourceDataField(serializers.JSONField):
    """
    Inspects the content object. If it has a managed serializer,
    serialize the data using it.
    """

    def to_representation(self, resource):
        resource_config = resource.content_type.resource_type.get_resource_config()
        if serializer := resource_config.get("managed_serializer"):
            return serializer(resource.content_object).data
        return {}

    # def to_internal_value(self, data):
    #     pass


class ResourceSerializer(serializers.ModelSerializer):
    # parents = serializers.SerializerMethodField()
    shared_resource_type = serializers.SerializerMethodField()
    is_externally_managed = serializers.BooleanField(source="content_type.resource_type.externally_managed", read_only=True)
    resource_data = ResourceDataField(source="*")

    class Meta:
        model = Resource
        read_only_fields = ["object_id", "name", "ansible_id"]
        fields = [
            "object_id",
            "name",
            "ansible_id",
            "resource_type",
            "is_externally_managed",
            "shared_resource_type",
            "resource_data",
        ]

    def get_content_type(self, obj):
        # TODO: n+1 query
        return obj.content_type.resource_type.resource_type

    def get_parents(self, obj):
        parents = []
        for r in obj.get_parents():
            parents.append(r.ansible_id)
        return parents

    def get_shared_resource_type(self, obj):
        if serializer := obj.content_type.resource_type.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None


class ResourceTypeSerializer(serializers.ModelSerializer):
    # permissions = serializers.SerializerMethodField()
    # inherited_permissions = serializers.SerializerMethodField()
    shared_resource_type = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "resource_type", "externally_managed", "shared_resource_type"]

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None
