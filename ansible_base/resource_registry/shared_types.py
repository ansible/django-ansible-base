from rest_framework import serializers


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
