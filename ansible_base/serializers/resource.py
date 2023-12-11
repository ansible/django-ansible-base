import logging
import re
import uuid

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.reverse import reverse_lazy

from ansible_base.models import PostgresTransaction, Resource, ResourceType
from ansible_base.utils.transactions import create_transaction

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


class DestroyResourceSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField(write_only=True, required=False)


class TransactionSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        read_only_fields = [
            "gid",
            "prepared",
        ]
        model = PostgresTransaction
        fields = ["gid", "prepared", "url"]

    def get_url(self, obj):
        return reverse_lazy('postgrestransaction-detail', kwargs={"gid": obj.gid})


class ResourceSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()
    is_externally_managed = serializers.BooleanField(source="content_type.resource_type.externally_managed", read_only=True)
    resource_data = ResourceDataField(source="*")
    resource_type = serializers.CharField()
    detail_url = serializers.SerializerMethodField()
    transaction_id = serializers.UUIDField(write_only=True, allow_null=True, required=False)
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
            "resource_type",
            "is_externally_managed",
            "shared_resource_type",
            "resource_data",
            "detail_url",
            "url",
            "transaction_id",
        ]

    def get_url(self, obj):
        return reverse_lazy('resource-detail', kwargs={"_ansible_id": obj.ansible_id})

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

                if t_id := validated_data.get("transaction_id"):
                    create_transaction(t_id)

            return instance

        raise serializers.ValidationError(
            {"resource_type": _(f"Resource type: {instance.content_type.resource_type.resource_type} cannot be managed by this API.")}
        )

    # allow setting ansible ID at create time
    def create(self, validated_data):
        try:
            r_type = ResourceType.objects.get(resource_type=validated_data["resource_type"])
            if not r_type.serializer_class:
                raise serializers.ValidationError({"resource_type": _(f"Resource type: {validated_data['resource_type']} cannot be managed by this API.")})

            c_type = r_type.content_type
            resource_data = self.get_resource_data(validated_data["resource_data"], r_type.serializer_class)

            with transaction.atomic():
                resource = c_type.model_class().objects.create(**resource_data)
                resource.save()

                if ansible_id := validated_data.get("ansible_id"):
                    Resource.objects.update_or_create(object_id=resource.pk, content_type=c_type, defaults={"ansible_id": ansible_id})

                if t_id := validated_data.get("transaction_id"):
                    create_transaction(t_id)
                    return True

            return Resource.objects.get(object_id=resource.pk, content_type=c_type)

        except ResourceType.DoesNotExist:
            raise serializers.ValidationError({"resource_type": _(f"Resource type: {validated_data['resource_type']} does not exist.")})

    def save(self, **kwargs):
        instance = super().save(**kwargs)
        if t_id := self.validated_data.get("transaction_id", False):
            self._data = {"transaction": t_id, "vote_commit": True}
            return None
        else:
            return instance


class ResourceTypeSerializer(serializers.ModelSerializer):
    shared_resource_type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = ResourceType
        fields = ["id", "resource_type", "externally_managed", "shared_resource_type", "url"]

    def get_shared_resource_type(self, obj):
        if serializer := obj.get_resource_config().get("managed_serializer"):
            return serializer.RESOURCE_TYPE
        else:
            return None

    def get_url(self, obj):
        return reverse_lazy('resourcetype-detail', kwargs={"resource_type": obj.resource_type})
