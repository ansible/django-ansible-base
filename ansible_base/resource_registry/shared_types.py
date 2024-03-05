from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ansible_base.resource_registry.models import Resource


class AnsibleResourceForeignKeyField(serializers.UUIDField):
    default_error_messages = {
        'invalid': _('Must be a valid UUID.'),
        'does_not_exist': _('Invalid ansible id "{ansible_id}" - resource does not exist.'),
    }

    def __init__(self, resource_type, **kwargs):
        self.resource_type = resource_type
        super().__init__(**kwargs)

    # Convert ansible ID to internal object ID
    def to_internal_value(self, data):
        ansible_id = super().to_internal_value(data)

        try:
            resource = Resource.objects.get(content_type__resource_type__name=self.resource_type, ansible_id=ansible_id)
        except Resource.DoesNotExist:
            self.fail('does_not_exist', ansible_id=data)

        return resource.content_object

    def get_attribute(self, instance):
        self.field_name
        obj_pk = getattr(instance, self.field_name).pk
        resource = Resource.objects.get(content_type__resource_type__name=self.resource_type, object_id=obj_pk)

        return resource.ansible_id


class UserType(serializers.Serializer):
    RESOURCE_TYPE = "user"

    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_superuser = serializers.BooleanField(default=False)
    # Commenting this out for now because Galaxy NG doesn't have a system auditor flag
    # is_system_auditor = serializers.BooleanField()


class OrganizationType(serializers.Serializer):
    RESOURCE_TYPE = "organization"

    name = serializers.CharField()


class TeamType(serializers.Serializer):
    RESOURCE_TYPE = "team"

    name = serializers.CharField()
    organization = AnsibleResourceForeignKeyField("shared.organization")
