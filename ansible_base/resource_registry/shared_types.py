from rest_framework import serializers

class UserType(serializers.Serializer):
    RESOURCE_TYPE = "user"

    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_superuser = serializers.BooleanField()
    is_system_auditor = serializers.BooleanField()


class OrganizationType(serializers.Serializer):
    RESOURCE_TYPE = "organization"

    name = serializers.CharField()


class TeamType(serializers.Serializer):
    RESOURCE_TYPE = "team"

    name = serializers.CharField()
