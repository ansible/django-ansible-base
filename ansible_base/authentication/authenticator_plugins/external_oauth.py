import json
import logging
import ssl
import urllib.error
import urllib.request

from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.lib.serializers.fields import BooleanField, CharField, IntegerField, ListField, URLField
from ansible_base.lib.serializers.validators import JWTAlgorithmListFieldValidator, asymmetric_jwt_algorithms

logger = logging.getLogger("ansible_base.authentication.authenticator_plugins.external_oauth")

OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"
OIDC_DISCOVERY_TIMEOUT_SECONDS = 30

_BASELINE_ATTRIBUTES = [
    "email",
    "preferred_username",
    "sub",
    "upn",
    "azp",
    "client_id",
    "groups",
]


def oidc_discovery_url(oidc_endpoint: str) -> str:
    return f"{oidc_endpoint.rstrip('/')}{OIDC_DISCOVERY_PATH}"


def fetch_oidc_discovery(oidc_endpoint: str, verify_ssl: bool = True) -> dict:
    """
    Fetch the OIDC discovery document at save time.

    Raises ValidationError keyed on OIDC_ENDPOINT for network, JSON, or content failures.
    """
    url = oidc_discovery_url(oidc_endpoint)
    context = ssl.create_default_context()
    if not verify_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, context=context, timeout=OIDC_DISCOVERY_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        logger.warning("OIDC discovery HTTP error for %s: %s", url, exc)
        raise ValidationError({"OIDC_ENDPOINT": _("Unable to fetch OIDC discovery document: HTTP %(status)s.") % {"status": exc.code}}) from exc
    except urllib.error.URLError as exc:
        logger.warning("OIDC discovery network error for %s: %s", url, exc)
        raise ValidationError({"OIDC_ENDPOINT": _("Unable to reach OIDC discovery endpoint.")}) from exc
    except TimeoutError as exc:
        logger.warning("OIDC discovery timed out for %s: %s", url, exc)
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery request timed out.")}) from exc

    try:
        document = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document is not valid JSON.")}) from exc

    if not isinstance(document, dict):
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document must be a JSON object.")})

    return document


def apply_oidc_discovery(attrs: dict) -> dict:
    """
    When OIDC_ENDPOINT is set, fetch discovery and populate JWKS_URI / USERINFO_URL.

    OIDC_ENDPOINT takes precedence over any manually provided JWKS_URI or USERINFO_URL.
    Missing userinfo_endpoint is allowed; missing jwks_uri is a validation error.
    """
    oidc_endpoint = attrs.get("OIDC_ENDPOINT") or ""
    if not oidc_endpoint:
        return attrs

    verify_ssl = attrs.get("VERIFY_SSL", True)
    document = fetch_oidc_discovery(oidc_endpoint, verify_ssl=bool(verify_ssl))

    jwks_uri = document.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri.strip():
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document is missing jwks_uri.")})

    attrs["JWKS_URI"] = jwks_uri.strip()

    userinfo_endpoint = document.get("userinfo_endpoint")
    if isinstance(userinfo_endpoint, str) and userinfo_endpoint.strip():
        attrs["USERINFO_URL"] = userinfo_endpoint.strip()

    return attrs


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
            "When OIDC_ENDPOINT is set, JWKS_URI is auto-populated from discovery at save time."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_("JWKS URI"),
    )

    ALLOWED_ALGORITHMS = ListField(
        help_text=_("Allowed JWT signing algorithms. Asymmetric algorithms only; 'none' and HMAC (HS*) are rejected."),
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

    # Min 60 / default 3600 come from the ANSTRAT-1611 P1 configuration schema.
    JWKS_CACHE_TIMEOUT = IntegerField(
        help_text=_(
            "How long to cache JWKS keys, in seconds. Minimum 60 to avoid hammering the "
            "provider's JWKS endpoint. No maximum — longer TTLs are fine for stable IdPs; "
            "token validation refreshes keys on signature failure so rotation still works."
        ),
        default=3600,
        allow_null=False,
        validators=[MinValueValidator(60)],
        ui_field_label=_("JWKS Cache Timeout (seconds)"),
    )

    CLAIM_LIST = ListField(
        help_text=_(
            "Ordered JWT claim keys used to resolve the external identity. "
            "No assumed default — configure explicitly. "
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
        help_text=_(
            "Optional UserInfo endpoint fetched after JWT validation to retrieve supplementary claims "
            "(for example group memberships). Auto-populated from OIDC discovery when present."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        ui_field_label=_("UserInfo URL"),
    )

    OIDC_ENDPOINT = URLField(
        help_text=_(
            "Base URL for OIDC auto-discovery. At save time, fetches /.well-known/openid-configuration "
            "to populate JWKS_URI (required in the document) and USERINFO_URL when present. "
            "Either JWKS_URI or OIDC_ENDPOINT must be provided. Not used at runtime."
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
        errors = {}
        jwks_uri = attrs.get("JWKS_URI") or ""
        oidc_endpoint = attrs.get("OIDC_ENDPOINT") or ""

        if not jwks_uri and not oidc_endpoint:
            message = _("Either JWKS_URI or OIDC_ENDPOINT must be provided.")
            errors["JWKS_URI"] = message
            errors["OIDC_ENDPOINT"] = message

        claim_list = attrs.get("CLAIM_LIST") or []
        invalid_claims = [claim for claim in claim_list if not isinstance(claim, str) or not claim.strip()]
        if invalid_claims:
            errors["CLAIM_LIST"] = _("CLAIM_LIST entries must be non-empty strings.")

        if errors:
            raise ValidationError(errors)

        attrs["CLAIM_LIST"] = [claim.strip() for claim in claim_list]

        if oidc_endpoint:
            # OIDC_ENDPOINT takes precedence: discovery overwrites JWKS_URI / USERINFO_URL.
            attrs = apply_oidc_discovery(attrs)

        return attrs


def _scalar_claim_uid(value) -> str | None:
    """Return a uid for string/int claim values; skip bool, float, and non-scalars.

    bool is checked before int because bool is an int subclass in Python.
    """
    if value is None or isinstance(value, (bool, float, dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, int):
        return str(value)
    return None


def resolve_uid_from_claims(claims: dict, claim_list: list) -> str | None:
    """
    Resolve an external identity from token claims using CLAIM_LIST order.

    The first present, non-empty string or integer claim value wins. Supports both
    human-user claim shapes (email, sub, preferred_username, upn) and service-principal
    shapes (azp, client_id) in a single ordered list. Bool, float, and non-scalar
    values (list/dict) are skipped rather than coerced into a uid.
    """
    if not claims or not claim_list:
        return None

    for claim_name in claim_list:
        if claim_name not in claims:
            continue
        uid = _scalar_claim_uid(claims[claim_name])
        if uid is not None:
            return uid

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
