import logging

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ansible_base.models import Resource, ResourceType

logger = logging.getLogger('ansible_base.serializers')


def get_resource_detail_view(resource: Resource):
    # TODO: format this so that it uses the correct API base path for the gateway.
    actions = resource.content_type.resource_type.get_resource_config().get("actions")

    # TODO: this needs some more logic to handle cases where the detail view isn't
    # name or pk, and in cases where there may be multiple detail views (such as with
    # nested API views). This may be solveable by providing a reverse_url_name when
    # resources are registered.
    if detail := actions.get("retrieve"):
        return detail[0][1].format(pk=resource.pk, name=resource.name)

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
    # parents = serializers.SerializerMethodField()
    shared_resource_type = serializers.SerializerMethodField()
    is_externally_managed = serializers.BooleanField(source="content_type.resource_type.externally_managed", read_only=True)
    resource_data = ResourceDataField(source="*")
    resource_type = serializers.CharField()
    detail_url = serializers.SerializerMethodField()
    # ansible_id = serializers.SerializerMethodField()

    class Meta:
        model = Resource
        read_only_fields = ["object_id", "name", "ansible_id"]
        fields = [
            "object_id",
            "name",
            "ansible_id",
            # "service_id",
            # "service_short_id",
            "resource_type",
            "is_externally_managed",
            "shared_resource_type",
            "resource_data",
            "detail_url",
        ]

    def get_ansible_id(self, obj):
        return f"{obj.service_short_id}:{obj.ansible_id}"

    def get_detail_url(self, obj):
        return get_resource_detail_view(obj)

    def get_shared_resource_type(self, obj):
        if serializer := obj.content_type.resource_type.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None

    def get_resource_data(self, resource_data, serializer):
        resource_data = serializer(data=resource_data)
        resource_data.is_valid(raise_exception=True)
        return resource_data.data

    def update(self, instance, validated_data):
        if serializer := instance.content_type.resource_type.serializer_class:
            with transaction.atomic():
                resource = instance.content_object
                resource_data = self.get_resource_data(validated_data["resource_data"], serializer)
                for k, val in resource_data.items():
                    setattr(resource, k, val)
                resource.save()

            instance.refresh_from_db()
            return instance

        raise serializers.ValidationError(
            {"resource_type": _(f"Resource type: {instance.content_type.resource_type.resource_type} cannot be managed by this API.")}
        )

    def create(self, validated_data):
        try:
            r_type = ResourceType.objects.get(resource_type=validated_data["resource_type"])
            if not r_type.serializer_class:
                raise serializers.ValidationError({"resource_type": _(f"Resource type: {validated_data['resource_type']} cannot be managed by this API.")})

            c_type = r_type.content_type
            resource_data = self.get_resource_data(validated_data["resource_data"], r_type.serializer_class)

            # putting this in a transaction to ensure the post save signal fires before we load the
            # object's Resource instance.
            with transaction.atomic():
                resource = c_type.model_class().objects.create(**resource_data)
                resource.save()

            return Resource.objects.get(object_id=resource.pk, content_type=c_type)

        except ResourceType.DoesNotExist:
            raise serializers.ValidationError({"resource_type": _(f"Resource type: {validated_data['resource_type']} does not exist.")})


class ResourceTypeSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "resource_type", "externally_managed", "shared_resource_type"]

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None
