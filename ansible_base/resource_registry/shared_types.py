from rest_framework import serializers

from ansible_base.resource_registry.utils.resource_type_serializers import (
    AnsibleResourceForeignKeyField,
    SharedResourceTypeSerializer,
)


class UserAdditionalDataSerializer(serializers.Serializer):
    """
    Additional data serializer for UserType
    """

    social_auth = serializers.ListField()

    def to_representation(self, instance):
        print("____------______-----____-----")
        social_auth = []

        if hasattr(instance, "authenticator_users"):
            print("authenticator type")
            for social in instance.authenticator_users.all():
                social_auth.append(
                    {
                        "social_backend": social.provider.type,
                        "social_uid": social.uid,
                    }
                )
        elif hasattr(instance, "social_auth"):
            print("social type")
            for social in instance.social_auth.all():
                social_auth.append(
                    {
                        "social_backend": social.provider,
                        "social_uid": social.uid,
                    }
                )
        else:
            print("???")

        return {"social_auth": social_auth}


class UserType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "user"
    ADDITIONAL_DATA_SERIALIZER = UserAdditionalDataSerializer

    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_superuser = serializers.BooleanField(default=False)
    # Commenting this out for now because Galaxy NG doesn't have a system auditor flag
    # is_platform_auditor = serializers.BooleanField()


class OrganizationType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "organization"

    name = serializers.CharField()
    description = serializers.CharField(
        default="",
        allow_blank=True,
    )


class TeamType(SharedResourceTypeSerializer):
    RESOURCE_TYPE = "team"

    name = serializers.CharField()
    organization = AnsibleResourceForeignKeyField("shared.organization", required=False, allow_null=True)
    description = serializers.CharField(
        default="",
        allow_blank=True,
    )
