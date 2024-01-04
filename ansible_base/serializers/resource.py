import logging
import re
import uuid

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.reverse import reverse_lazy

from ansible_base.models import Resource, ResourceType

logger = logging.getLogger('ansible_base.serializers')

ANSIBLE_ID_REGEX = re.compile(r"^[0-9a-fA-F]{8}:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def get_resource_detail_view(resource: Resource):
    # TODO: format this so that it uses the correct API base path for the gateway.
    actions = resource.content_type.resource_type.get_resource_config().get("actions")

    # TODO: this needs some more logic to handle cases where the detail view isn't
    # name or pk, and in cases where there may be multiple detail views (such as with
    # nested API views). This may be solvable by providing a reverse_url_name when
    # resources are registered.
    if detail := actions.get("retrieve"):
        return detail[0][1].format(pk=resource.object_id, name=resource.name)

    return None


def ansible_id_validator(val):
    message = _(
        "Ansible ID must in the format of <service_id>:<resource_id>, "
        "where service_id is the first 8 characters of the service's ID "
        "and resource_id is a valid UUID 4."
    )

    if not ANSIBLE_ID_REGEX.match(val):
        raise serializers.ValidationError(message)

    (s_id, r_id) = val.split(":")

    try:
        if str(uuid.UUID(r_id, version=4)) != r_id:
            raise serializers.ValidationError(message)
    except ValueError:
        raise serializers.ValidationError(message)


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
    name = serializers.CharField()
    detail_url = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    ansible_id = serializers.CharField(validators=[ansible_id_validator], required=False)

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
            "name",
            "has_serializer",
            "resource_data",
            "detail_url",
            "url",
        ]

    def get_url(self, obj):
        return reverse_lazy('resource-detail', kwargs={"_ansible_id": obj.ansible_id})

    def get_detail_url(self, obj):
        return get_resource_detail_view(obj)

    def get_has_serializer(self, obj):
        return bool(obj.content_type.resource_type.get_resource_config().get("managed_serializer", False))

    def get_resource_data(self, resource_data, serializer):
        resource_data = serializer(data=resource_data)
        resource_data.is_valid(raise_exception=True)
        return resource_data.data

    # update ansible ID
    def update(self, instance, validated_data):
        if serializer := instance.content_type.resource_type.serializer_class:
            with transaction.atomic():
                resource = instance.content_object
                resource_data = self.get_resource_data(validated_data["resource_data"], serializer)
                for k, val in resource_data.items():
                    setattr(resource, k, val)
                resource.save()

                if ansible_id := validated_data.get("ansible_id"):
                    instance.ansible_id = ansible_id
                    instance.save()

            return instance

        raise serializers.ValidationError({"name": _(f"Resource type: {instance.content_type.resource_type.type_name} cannot be managed by this API.")})

    # allow setting ansible ID at create time
    def create(self, validated_data):
        try:
            r_type = ResourceType.objects.get(type_name=validated_data["name"])
            if not r_type.serializer_class:
                raise serializers.ValidationError({"name": _(f"Resource type: {validated_data['name']} cannot be managed by this API.")})

            c_type = r_type.content_type
            resource_data = self.get_resource_data(validated_data["resource_data"], r_type.serializer_class)

            with transaction.atomic():
                resource = c_type.model_class().objects.create(**resource_data)
                resource.save()

                if ansible_id := validated_data.get("ansible_id"):
                    Resource.objects.update_or_create(object_id=resource.pk, content_type=c_type, defaults={"ansible_id": ansible_id})

            return Resource.objects.get(object_id=resource.pk, content_type=c_type)

        except ResourceType.DoesNotExist:
            raise serializers.ValidationError({"name": _(f"Resource type: {validated_data['name']} does not exist.")})


class ResourceTypeSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "name", "externally_managed", "shared_resource_type", "url"]

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None

    def get_url(self, obj):
        return reverse_lazy('resourcetype-detail', kwargs={"name": obj.type_name})
