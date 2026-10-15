import logging

from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.lib.serializers.fields import BooleanField, CharField, IntegerField, ListField, URLField
from ansible_base.lib.serializers.validators import JWTAlgorithmListFieldValidator, asymmetric_jwt_algorithms

logger = logging.getLogger("ansible_base.authentication.authenticator_plugins.external_oauth")

_BASELINE_ATTRIBUTES = [
    "email",
    "preferred_username",
    "sub",
    "upn",
    "azp",
    "client_id",
    "groups",
]


class ExternalOAuthConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://openid.net/specs/openid-connect-discovery-1_0.html"

    ISSUER_URL = URLField(
        help_text=_("Provider issuer URL. Must match the 'iss' claim in validated JWT tokens."),
        allow_null=False,
        ui_field_label=_("Issuer URL"),
    )

    JWKS_URI = URLField(
        help_text=_(
            "Provider JWKS endpoint used to verify JWT signatures. "
            "Either JWKS_URI or OIDC_ENDPOINT must be provided. "
            "OIDC discovery can later auto-populate this field from OIDC_ENDPOINT."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_("JWKS URI"),
    )

    ALLOWED_ALGORITHMS = ListField(
        help_text=_(
            "Allowed JWT signing algorithms for this provider. " "Only asymmetric algorithms are permitted (RS*/ES*/PS*/EdDSA); " "'none' and HS* are rejected."
        ),
        default=["RS256"],
        allow_null=False,
        allow_empty=False,
        validators=[JWTAlgorithmListFieldValidator(allowed_values=asymmetric_jwt_algorithms)],
        ui_field_label=_("Allowed Algorithms"),
    )

    AUDIENCE = CharField(
        help_text=_(
            "Expected 'aud' claim value (exact match). Required so tokens issued "
            "for another application in the same IdP tenant cannot be replayed against AAP."
        ),
        allow_null=False,
        allow_blank=False,
        ui_field_label=_("Audience"),
    )

    JWKS_CACHE_TIMEOUT = IntegerField(
        help_text=_("JWKS cache duration in seconds. Minimum 60."),
        default=3600,
        allow_null=False,
        validators=[MinValueValidator(60)],
        ui_field_label=_("JWKS Cache Timeout"),
    )

    CLAIM_LIST = ListField(
        help_text=_(
            "Ordered JWT claim keys used to resolve the external identity "
            "(AuthenticatorUser.uid). No assumed default — configure explicitly. "
            "The first claim present in the token wins. "
            'Example for Entra ID: ["email", "azp"] (human users and service principals).'
        ),
        required=True,
        allow_null=False,
        allow_empty=False,
        ui_field_label=_("Claim List"),
    )

    # Default matches AzureAD / Entra ID ("groups"). OIDC SSO uses "Group" for
    # historical reasons; keep provider-appropriate defaults rather than forcing one.
    GROUPS_CLAIM = CharField(
        help_text=_("JWT or UserInfo claim key used to extract group memberships for authenticator maps."),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="groups",
        ui_field_label=_("Groups Claim"),
    )

    USERINFO_URL = URLField(
        help_text=_("Optional UserInfo endpoint fetched after JWT validation to retrieve supplementary claims (for example group memberships)."),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_("UserInfo URL"),
    )

    OIDC_ENDPOINT = URLField(
        help_text=_(
            "Base URL for OIDC auto-discovery (/.well-known/openid-configuration). "
            "Either JWKS_URI or OIDC_ENDPOINT must be provided. "
            "Save-time discovery to populate JWKS_URI/USERINFO_URL is a follow-up; "
            "this field is accepted now so configs can be stored ahead of that work."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_("OIDC Discovery Endpoint"),
    )

    VERIFY_SSL = BooleanField(
        help_text=_("Verify the OAuth provider SSL certificate for outbound requests (JWKS, OIDC discovery, UserInfo)."),
        default=True,
        allow_null=False,
        ui_field_label=_("Verify SSL Certificate"),
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        jwks_uri = attrs.get("JWKS_URI") or ""
        oidc_endpoint = attrs.get("OIDC_ENDPOINT") or ""

        if not jwks_uri and not oidc_endpoint:
            raise ValidationError(
                {
                    "JWKS_URI": _("Either JWKS_URI or OIDC_ENDPOINT must be provided."),
                    "OIDC_ENDPOINT": _("Either JWKS_URI or OIDC_ENDPOINT must be provided."),
                }
            )

        claim_list = attrs.get("CLAIM_LIST") or []
        invalid_claims = [claim for claim in claim_list if not isinstance(claim, str) or not claim.strip()]
        if invalid_claims:
            raise ValidationError({"CLAIM_LIST": _("CLAIM_LIST entries must be non-empty strings.")})

        # Normalize whitespace while preserving declared order.
        attrs["CLAIM_LIST"] = [claim.strip() for claim in claim_list]
        return attrs


def resolve_uid_from_claims(claims: dict, claim_list: list) -> str | None:
    """
    Resolve an external identity from token claims using CLAIM_LIST order.

    The first present, non-empty scalar claim value wins. Supports both human-user
    claim shapes (email, sub, preferred_username, upn) and service-principal
    shapes (azp, client_id) in a single ordered list. Non-scalar values (list/dict)
    are skipped as misconfiguration rather than coerced into a uid.
    """
    if not claims or not claim_list:
        return None

    for claim_name in claim_list:
        if claim_name not in claims:
            continue
        value = claims[claim_name]
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)

    return None


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    configuration_class = ExternalOAuthConfiguration
    type = "external_oauth"
    category = "api_auth"
    logger = logger
    configuration_encrypted_fields = []

    def get_login_url(self, authenticator):
        return None

    def get_default_attributes(self):
        """Attributes available for authenticator maps.

        Prefer the configured CLAIM_LIST + GROUPS_CLAIM when a database instance
        is attached; otherwise fall back to a common baseline of claim names.
        """
        if not self.database_instance:
            return list(_BASELINE_ATTRIBUTES)

        config = self.database_instance.configuration or {}
        attrs = []
        for claim in config.get("CLAIM_LIST") or []:
            if isinstance(claim, str) and claim.strip() and claim not in attrs:
                attrs.append(claim.strip())
        groups_claim = config.get("GROUPS_CLAIM") or "groups"
        if isinstance(groups_claim, str) and groups_claim.strip() and groups_claim not in attrs:
            attrs.append(groups_claim.strip())
        return attrs or list(_BASELINE_ATTRIBUTES)
