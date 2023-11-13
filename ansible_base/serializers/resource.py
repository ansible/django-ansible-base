import logging

from rest_framework import serializers
from ansible_base.models import Resource, Permission, ResourceType

from django.db.models import Q

logger = logging.getLogger('ansible_base.serializers')


class ResourceSerializer(serializers.ModelSerializer):
    content_type = serializers.SerializerMethodField()
    parents = serializers.SerializerMethodField()

    # actions = serializers.SerializerMethodField()
    class Meta:
        model = Resource
        fields = ["object_id", "ansible_id", "content_type", "parents"]

    def get_content_type(self, obj):
        # TODO: n+1 query
        return obj.content_type.resource_type.resource_type

    def get_actions(self, obj):
        return obj.content_type.resource_type.get_resource_config()

    def get_parents(self, obj):
        parents = []
        for r in obj.get_parents():
            parents.append(r.ansible_id)
        return parents


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
        print(obj.action)
        return obj.resource_type.get_resource_config()["actions"].get(obj.action, [])


class ResourceTypeSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    inherited_permissions = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "resource_type", "externally_managed", "parent_types", "child_types", "permissions", "inherited_permissions"]

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
