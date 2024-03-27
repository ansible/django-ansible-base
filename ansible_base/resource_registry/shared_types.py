#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

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
        # If the model doesn't have an attribute with the given field name, return None. This is
        # mostly here to keep Hub from breaking, which doesn't have organizations yet.
        obj = getattr(instance, self.field_name, None)
        if obj is None:
            return None
        resource = Resource.objects.get(content_type__resource_type__name=self.resource_type, object_id=obj.pk)

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
    organization = AnsibleResourceForeignKeyField("shared.organization", required=False, allow_null=True)
