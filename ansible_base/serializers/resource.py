import logging

from rest_framework import serializers
from ansible_base.models import Resource, Permission, ResourceType

from django.db.models import Q

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
    content_type = serializers.SerializerMethodField()
    parents = serializers.SerializerMethodField()
    shared_resource_type = serializers.SerializerMethodField()
    is_externally_managed = serializers.BooleanField(source="content_type.resource_type.externally_managed", read_only=True)
    resource_data = ResourceDataField(source="*")

    class Meta:
        model = Resource
        read_only_fields = ["object_id", "resource_hash"]
        fields = ["object_id", "ansible_id", "content_type", "parents", "is_externally_managed", "shared_resource_type", "resource_hash", "resource_data", ]

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

class ResourcePermissionSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    api_calls = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ["name", "api_calls"]

    def get_name(self, obj):
        # TODO: n+1 query
        return f"{obj.resource_type.resource_type}:{obj.action}"

    def get_api_calls(self, obj):
        # TODO: n+1 query
        return obj.resource_type.get_resource_config()["actions"].get(obj.action, [])


class ResourceTypeSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    inherited_permissions = serializers.SerializerMethodField()
    shared_resource_type = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "resource_type", "externally_managed", "shared_resource_type", "parent_types", "child_types", "permissions", "inherited_permissions"]

    def get_permissions(self, obj):
        return ResourcePermissionSerializer(Permission.objects.filter(resource_type=obj), many=True).data

    def get_inherited_permissions(self, obj):
        filter = Q()

        children = obj.get_all_child_types()
        if len(children) == 0:
            return []
        for child_type in children:
            print(child_type)
            app_label, model = child_type.lower().split(".")
            filter = filter | Q(resource_type__content_type__app_label=app_label, resource_type__content_type__model=model)

        return ResourcePermissionSerializer(Permission.objects.filter(filter), many=True).data

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None