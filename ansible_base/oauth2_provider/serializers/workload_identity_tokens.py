from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class WorkloadIdentityTokenRequestSerializer(serializers.Serializer):
    """
    Serializer for workload identity token request payload.
    Validates that scope, audience, and claims are properly provided.
    """

    scope = serializers.CharField(
        required=True,
        allow_null=False,
        allow_blank=False,
        help_text=_("OIDC Scope for the token. Supported scopes can be discovered at the well-known OIDC GW endpoints."),
    )
    audience = serializers.CharField(
        required=True,
        allow_null=False,
        allow_blank=False,
        help_text=_("The intended audience (aud claim) for the JWT. Typically the identifier of the resource server that will consume this token."),
    )
    claims = serializers.DictField(
        required=True,
        allow_empty=False,
        help_text=_("Workload details to include in the JWT as claims. Must be a non-empty JSON object."),
    )

    def validate_claims(self, value):
        """
        Validate that claims is a non-empty dictionary.
        """
        message = _("Workload details must be a non-empty JSON object")
        if not isinstance(value, dict):
            raise serializers.ValidationError(message)
        if len(value.keys()) == 0:
            raise serializers.ValidationError(message)
        return value


class WorkloadIdentityTokenResponseSerializer(serializers.Serializer):
    """
    Serializer for workload identity token response.
    """

    jwt = serializers.CharField(
        help_text=_("The signed JWT token for workload identity."),
    )
