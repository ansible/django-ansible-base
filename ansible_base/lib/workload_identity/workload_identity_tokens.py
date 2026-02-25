from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

# Hard ceiling for workload-specific TTL overrides. 24 hours is intentionally
# generous — workloads needing longer lifetimes should reconsider their design.
# Terraform Cloud ties exp to the run timeout with no imposed ceiling for workspace
# runs, but does enforce a max (30 min) for module test tokens. We follow the
# bounded approach here as a safety net against misconfigured or unlimited timeouts.
# See: https://developer.hashicorp.com/terraform/cloud-docs/dynamic-provider-credentials/workload-identity-tokens
# A preference-driven maximum can replace this constant in a follow-up.
WORKLOAD_TTL_MAX_SECONDS = 24 * 60 * 60  # 86400 or 24 hours


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
        help_text=_("Workload details to include in the JWT as claims."),
    )
    workload_ttl_seconds = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=WORKLOAD_TTL_MAX_SECONDS,
        help_text=_(
            f"Optional workload-specific TTL override in seconds (1–{WORKLOAD_TTL_MAX_SECONDS}). "
            "If provided, overrides the platform default for this token. "
            "Omit or set to null to use the platform fallback (jwt_default_ttl_seconds). "
            "A 60s clock skew offset is automatically added to all JWTs."
        ),
    )


class WorkloadIdentityTokenResponseSerializer(serializers.Serializer):
    """
    Serializer for workload identity token response.
    """

    jwt = serializers.CharField(
        help_text=_("The signed JWT token for workload identity."),
    )
