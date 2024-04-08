from rest_framework import serializers

from ansible_base.resource_registry.utils.resource_type_serializers import (
    AnsibleResourceForeignKeyField,
    AnsibleResourceManyRelated,
    SharedResourceTypeSerializer,
)


class UserAdditionalDataSerializer(serializers.Serializer):
    """
    Additional data serializer for UserType
    """

    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_superuser = serializers.BooleanField(default=False)

    # If this user is an SSO user, provide
    external_auth_provider = serializers.CharField(required=False, allow_blank=True)
    external_auth_uid = serializers.CharField(required=False, allow_blank=True)

    organizations = AnsibleResourceManyRelated("shared.organization")
    organizations_administered = serializers.SerializerMethodField()

    teams = AnsibleResourceManyRelated("shared.team")
    teams_administered = serializers.SerializerMethodField()

    def get_organizations_administered(self, obj):
        if not hasattr(obj, "organizations_administered"):
            return []
        ansible_resources_serializer = AnsibleResourceManyRelated("shared.organization")
        return ansible_resources_serializer.to_representation(obj.organizations_administered)

    def get_teams_administered(self, obj):
        if not hasattr(obj, "teams_administered"):
            return []
        ansible_resources_serializer = AnsibleResourceManyRelated("shared.team")
        return ansible_resources_serializer.to_representation(obj.organizations_administered)


class UserType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "user"
    ADDITIONAL_DATA_SERIALIZER = UserAdditionalDataSerializer

    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_superuser = serializers.BooleanField(default=False)
    # Commenting this out for now because Galaxy NG doesn't have a system auditor flag
    # is_system_auditor = serializers.BooleanField()


class OrganizationType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "organization"

    name = serializers.CharField()


class TeamType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "team"

    name = serializers.CharField()
    organization = AnsibleResourceForeignKeyField("shared.organization", required=False, allow_null=True)
