import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from jwt.algorithms import get_default_algorithms
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.lib.serializers.fields import BooleanField, CharField, IntegerField, ListField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.external_oauth')

DEFAULT_ALGORITHMS = get_default_algorithms()


class JWTAlgorithmListFieldValidator:
    allowed_values = list(DEFAULT_ALGORITHMS.keys())

    def __call__(self, value):
        if not all(item in self.allowed_values for item in value):
            raise DjangoValidationError(
                _('%(value)s contains items not in the allowed list: %(allowed_values)s'),
                params={'value': value, 'allowed_values': self.allowed_values},
            )


class ExternalOAuthConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://openid.net/specs/openid-connect-discovery-1_0.html"

    ISSUER_URL = URLField(
        help_text=_("Provider issuer URL. Must match the 'iss' claim in validated JWT tokens."),
        allow_null=False,
        ui_field_label=_('Issuer URL'),
    )

    JWKS_URI = URLField(
        help_text=_(
            "Provider JWKS endpoint used to verify JWT signatures. "
            "Either JWKS_URI or OIDC_ENDPOINT must be provided. "
            "When OIDC_ENDPOINT is provided, JWKS_URI may be auto-populated from discovery."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_('JWKS URI'),
    )

    ALLOWED_ALGORITHMS = ListField(
        help_text=_("Allowed JWT signing algorithms for this provider."),
        default=["RS256"],
        allow_null=False,
        allow_empty=False,
        validators=[JWTAlgorithmListFieldValidator()],
        ui_field_label=_('Allowed Algorithms'),
    )

    AUDIENCE = CharField(
        help_text=_("Expected 'aud' claim value. Strongly recommended. " "When empty, audience validation is skipped."),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_('Audience'),
    )

    JWKS_CACHE_TIMEOUT = IntegerField(
        help_text=_("JWKS cache duration in seconds. Minimum 60."),
        default=3600,
        allow_null=False,
        validators=[MinValueValidator(60)],
        ui_field_label=_('JWKS Cache Timeout'),
    )

    CLAIM_LIST = ListField(
        help_text=_(
            "Ordered JWT claim keys used to resolve the external identity "
            "(AuthenticatorUser.uid). No assumed default — configure explicitly. "
            "The first claim present in the token wins. "
            "Example for Entra ID: [\"email\", \"azp\"] (human users and service principals)."
        ),
        required=True,
        allow_null=False,
        allow_empty=False,
        ui_field_label=_('Claim List'),
    )

    GROUPS_CLAIM = CharField(
        help_text=_("JWT or UserInfo claim key used to extract group memberships for authenticator maps."),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="groups",
        ui_field_label=_('Groups Claim'),
    )

    USERINFO_URL = URLField(
        help_text=_("Optional UserInfo endpoint fetched after JWT validation to retrieve " "supplementary claims (for example group memberships)."),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_('UserInfo URL'),
    )

    OIDC_ENDPOINT = URLField(
        help_text=_(
            "Base URL for OIDC auto-discovery. Appends /.well-known/openid-configuration "
            "to auto-populate JWKS_URI (and USERINFO_URL when present). "
            "Either JWKS_URI or OIDC_ENDPOINT must be provided. Fetched at save time only."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_('OIDC Discovery Endpoint'),
    )

    VERIFY_SSL = BooleanField(
        help_text=_("Verify the OAuth provider SSL certificate for outbound requests (JWKS, OIDC discovery, UserInfo)."),
        default=True,
        allow_null=False,
        ui_field_label=_('Verify SSL Certificate'),
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        jwks_uri = attrs.get('JWKS_URI') or ''
        oidc_endpoint = attrs.get('OIDC_ENDPOINT') or ''

        if not jwks_uri and not oidc_endpoint:
            raise ValidationError(
                {
                    'JWKS_URI': _("Either JWKS_URI or OIDC_ENDPOINT must be provided."),
                    'OIDC_ENDPOINT': _("Either JWKS_URI or OIDC_ENDPOINT must be provided."),
                }
            )

        claim_list = attrs.get('CLAIM_LIST') or []
        invalid_claims = [claim for claim in claim_list if not isinstance(claim, str) or not claim.strip()]
        if invalid_claims:
            raise ValidationError({'CLAIM_LIST': _("CLAIM_LIST entries must be non-empty strings.")})

        # Normalize whitespace while preserving declared order.
        attrs['CLAIM_LIST'] = [claim.strip() for claim in claim_list]
        return attrs


def resolve_uid_from_claims(claims: dict, claim_list: list) -> str | None:
    """
    Resolve an external identity from token claims using CLAIM_LIST order.

    The first present, non-empty claim value wins. Supports both human-user
    claim shapes (email, sub, preferred_username, upn) and service-principal
    shapes (azp, client_id) in a single ordered list.
    """
    if not claims or not claim_list:
        return None

    for claim_name in claim_list:
        if claim_name not in claims:
            continue
        value = claims[claim_name]
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            return value
        # Non-string claim values are stringified for AuthenticatorUser.uid.
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
        return [
            "email",
            "preferred_username",
            "sub",
            "upn",
            "azp",
            "client_id",
            "groups",
        ]

    @staticmethod
    def resolve_uid(claims: dict, claim_list: list) -> str | None:
        return resolve_uid_from_claims(claims, claim_list)
