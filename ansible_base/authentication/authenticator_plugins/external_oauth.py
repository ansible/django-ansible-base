import logging
import ssl
from typing import Any

import requests
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _
from jwt import PyJWK, decode
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError, PyJWKClientConnectionError, PyJWKClientError, PyJWTError
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.bearer_authentication import BearerAuthenticationResult, BearerTokenValidationError, ScopedBearerToken
from ansible_base.authentication.jwk_client import CachedJWKClient
from ansible_base.authentication.utils.authentication import get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims
from ansible_base.authentication.utils.user import normalize_and_get_email
from ansible_base.lib.serializers.fields import BooleanField, CharField, IntegerField, ListField, URLField
from ansible_base.lib.serializers.validators import JWTAlgorithmListFieldValidator, asymmetric_jwt_algorithms
from ansible_base.lib.utils.models import is_system_user
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.validation import validate_url

logger = logging.getLogger("ansible_base.authentication.authenticator_plugins.external_oauth")
OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"
OIDC_DISCOVERY_TIMEOUT_SETTING = "ANSIBLE_BASE_EXTERNAL_OAUTH_DISCOVERY_TIMEOUT"
OIDC_DISCOVERY_TIMEOUT_DEFAULT = 30
OIDC_DISCOVERY_LOG_BODY_MAX = 512

_BASELINE_ATTRIBUTES = [
    "email",
    "preferred_username",
    "sub",
    "upn",
    "azp",
    "client_id",
    "groups",
]


def _local_oidc_issuer() -> str | None:
    """Return this deployment's OIDC issuer when DAB's optional provider is installed.

    External OAuth is reusable outside Gateway, so it deliberately knows only
    about DAB's optional OAuth2 provider configuration—not Gateway settings or
    Workload Identity.  A deployment without that provider has no local issuer
    to reserve.
    """
    if "ansible_base.oauth2_provider" not in settings.INSTALLED_APPS:
        return None

    oauth2_provider = get_setting("OAUTH2_PROVIDER", {})
    if not isinstance(oauth2_provider, dict):
        return None
    issuer = oauth2_provider.get("OIDC_ISS_ENDPOINT")
    return issuer.strip() if isinstance(issuer, str) and issuer.strip() else None


def oidc_discovery_url(oidc_endpoint: str) -> str:
    """Build the well-known discovery URL from a provider's configured endpoint."""
    return f"{oidc_endpoint.rstrip('/')}{OIDC_DISCOVERY_PATH}"


def _discovery_timeout() -> int:
    """Return the configured bounded timeout for save-time OIDC discovery requests."""
    return get_setting(OIDC_DISCOVERY_TIMEOUT_SETTING, OIDC_DISCOVERY_TIMEOUT_DEFAULT)


def _bounded_body_for_log(text: str) -> str:
    """Limit response bodies included in debug logs so malformed responses cannot flood logs."""
    if len(text) <= OIDC_DISCOVERY_LOG_BODY_MAX:
        return text
    return f"{text[:OIDC_DISCOVERY_LOG_BODY_MAX]}... (truncated)"


def _validate_discovered_url(value: str, field_name: str) -> str:
    """Run discovered endpoint URLs through the same validation as URLField."""
    value = value.strip()
    try:
        validate_url(value, schemes=["https"], allow_plain_hostname=True)
    except ValidationError as exc:
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery returned an invalid %(field)s.") % {"field": field_name}}) from exc
    return value


def fetch_oidc_discovery(oidc_endpoint: str, verify_ssl: bool = True) -> dict[str, Any]:
    """
    Fetch the OIDC discovery document at save time.

    Raises ValidationError keyed on OIDC_ENDPOINT for network, JSON, or content failures.
    """
    url = oidc_discovery_url(oidc_endpoint)
    timeout = _discovery_timeout()
    response = None

    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=timeout,
            verify=verify_ssl,
        )
        # Strict OIDC discovery responses are HTTP 200 (not other 2xx).
        if response.status_code != 200:
            logger.warning(f"OIDC discovery HTTP error for {url}: status {response.status_code}")
            raise ValidationError({"OIDC_ENDPOINT": _("Unable to fetch OIDC discovery document: HTTP %(status)s.") % {"status": response.status_code}})
        document = response.json()
    except requests.exceptions.Timeout as exc:
        logger.warning(f"OIDC discovery timed out for {url}: {exc}")
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery request timed out.")}) from exc
    except requests.exceptions.JSONDecodeError as exc:
        body = _bounded_body_for_log(response.text if response is not None else "")
        logger.debug(f"OIDC discovery invalid JSON from {url}: {exc}; body={body}")
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document is not valid JSON.")}) from exc
    except requests.exceptions.RequestException as exc:
        logger.warning(f"OIDC discovery network error for {url}: {exc}")
        raise ValidationError({"OIDC_ENDPOINT": _("Unable to reach OIDC discovery endpoint.")}) from exc

    if not isinstance(document, dict):
        logger.debug(
            "OIDC discovery non-object JSON from %s: type=%s body=%s",
            url,
            type(document).__name__,
            _bounded_body_for_log(repr(document)),
        )
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document must be a JSON object.")})

    return document


def apply_oidc_discovery(attrs: dict[str, Any]) -> dict[str, Any]:
    """
    When OIDC_ENDPOINT is set, fetch discovery and populate JWKS_URI / USERINFO_URL.

    OIDC_ENDPOINT is the source of truth on every save: discovery overwrites any
    manually submitted JWKS_URI or USERINFO_URL. Missing userinfo_endpoint is
    allowed; missing or invalid jwks_uri is a validation error.
    """
    oidc_endpoint = attrs.get("OIDC_ENDPOINT") or ""
    if not oidc_endpoint:
        return attrs

    verify_ssl = attrs.get("VERIFY_SSL", True)
    document = fetch_oidc_discovery(oidc_endpoint, verify_ssl=bool(verify_ssl))

    jwks_uri = document.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri.strip():
        raise ValidationError({"OIDC_ENDPOINT": _("OIDC discovery document is missing jwks_uri.")})

    attrs["JWKS_URI"] = _validate_discovered_url(jwks_uri, "jwks_uri")

    userinfo_endpoint = document.get("userinfo_endpoint")
    if isinstance(userinfo_endpoint, str) and userinfo_endpoint.strip():
        attrs["USERINFO_URL"] = _validate_discovered_url(userinfo_endpoint, "userinfo_endpoint")

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
            "When OIDC_ENDPOINT is set, this value is overwritten from discovery on every save."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        schemes=["https"],
        allow_plain_hostname=True,
        ui_field_label=_("JWKS URI"),
    )

    JWKS_URL_TIMEOUT = IntegerField(
        help_text=_("Timeout for JWKS URL requests in seconds."),
        default=30,
        allow_null=False,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        ui_field_label=_("JWKS URL Timeout"),
    )

    JWT_CLOCK_SKEW_TOLERANCE_SECONDS = IntegerField(
        help_text=_("Number of seconds after a token's expiration to continue accepting it. The same tolerance is applied to nbf and iat claims."),
        default=0,
        allow_null=False,
        validators=[MinValueValidator(0), MaxValueValidator(300)],
        ui_field_label=_("JWT Clock Skew Tolerance (seconds)"),
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
            "(for example group memberships). When OIDC_ENDPOINT is set and the discovery document "
            "includes userinfo_endpoint, this value is overwritten from discovery on every save."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        schemes=["https"],
        allow_plain_hostname=True,
        ui_field_label=_("UserInfo URL"),
    )

    OIDC_ENDPOINT = URLField(
        help_text=_(
            "Base URL for OIDC auto-discovery. At save time (every create/update while this field is "
            "set), fetches /.well-known/openid-configuration and overwrites JWKS_URI from jwks_uri "
            "(required) and USERINFO_URL from userinfo_endpoint when present. Discovery is the source "
            "of truth while OIDC_ENDPOINT remains set — clear it to manage JWKS_URI/USERINFO_URL "
            "manually. Either JWKS_URI or OIDC_ENDPOINT must be provided. Not used at runtime."
        ),
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        schemes=["https"],
        allow_plain_hostname=True,
        ui_field_label=_("OIDC Discovery Endpoint"),
    )

    VERIFY_SSL = BooleanField(
        help_text=_("Verify the OAuth provider SSL certificate for outbound requests (JWKS, OIDC discovery, UserInfo)."),
        default=True,
        allow_null=False,
        ui_field_label=_("Verify SSL Certificate"),
    )

    SCOPE_ATTRIBUTE_NAME = CharField(
        help_text=_("Name of the attribute to use for the scope claim. Defaults to 'scope'."),
        allow_blank=False,
        allow_null=False,
        default="scope",
        ui_field_label=_("Scope Attribute Name"),
    )

    WRITE_SCOPE_NAME = CharField(
        help_text=_("Valid tokens will have read scope by default. Name of the scope to use for the write claim. Defaults to 'write'."),
        allow_blank=False,
        allow_null=False,
        default="write",
        ui_field_label=_("Write Scope Name"),
    )

    READ_SCOPE_NAME = CharField(
        help_text=_("Name of the scope to use for the read claim. Defaults to 'read'."),
        allow_blank=False,
        allow_null=False,
        default="read",
        ui_field_label=_("Read Scope Name"),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate the configuration and populate discovery-owned endpoint values when enabled."""
        attrs = super().validate(attrs)
        errors = {}
        jwks_uri = attrs.get("JWKS_URI") or ""
        oidc_endpoint = attrs.get("OIDC_ENDPOINT") or ""

        if not jwks_uri and not oidc_endpoint:
            message = _("Either JWKS_URI or OIDC_ENDPOINT must be provided.")
            errors["JWKS_URI"] = message
            errors["OIDC_ENDPOINT"] = message

        local_issuer = _local_oidc_issuer()
        if local_issuer and attrs.get("ISSUER_URL") == local_issuer:
            errors["ISSUER_URL"] = _("An external OAuth issuer cannot be this deployment's local OIDC issuer.")

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


def _scalar_claim_uid(value: Any) -> str | None:
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


def resolve_uid_from_claims(claims: dict[str, Any], claim_list: list[str]) -> str | None:
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

    def get_login_url(self, authenticator: Any) -> None:
        """Return no login URL because bearer authentication has no browser redirect flow."""
        return None

    def get_default_attributes(self) -> list[str]:
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

    def _matches_token_routing_claims(self, token: str, configuration: dict[str, Any]) -> bool:
        """Return whether unverified routing claims identify this external OAuth provider.

        The dispatcher passes every Bearer token to each API authenticator.  This
        inexpensive check lets this JWT-specific plugin decline opaque tokens and
        tokens for other providers before it fetches JWKS data.  Issuer and
        audience are validated again, cryptographically, below; these claims are
        used here only to select a possible validator.
        """
        try:
            payload = decode(
                token,
                options={  # NOSONAR(S5659) -- routing selects a validator; _decode_validated_token verifies the JWT.
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except (PyJWTError, TypeError, ValueError) as exc:
            logger.debug(f"External OAuth token cannot be routed to an issuer: {exc}")
            return False

        # These values predate this plugin's schema migrations in some
        # installations.  A missing required value must decline routing, never
        # accidentally match an unverified token claim.
        issuer_url = configuration.get("ISSUER_URL")
        expected_audience = configuration.get("AUDIENCE")
        if not isinstance(issuer_url, str) or not issuer_url or not isinstance(expected_audience, str) or not expected_audience:
            return False

        if payload.get("iss") != issuer_url:
            return False

        audience = payload.get("aud")
        if isinstance(audience, str):
            return audience == expected_audience
        if isinstance(audience, list):
            # This is routing only. PyJWT performs the authoritative claim-type
            # and audience validation after this provider selects the token.
            return expected_audience in audience
        return False

    @staticmethod
    def _decode_validated_token(token: str, signing_key: Any, configuration: dict[str, Any]) -> dict[str, Any]:
        """Verify one JWT against a resolved signing key and provider configuration.

        The initial validation and one key-rotation retry intentionally share
        identical JWT requirements. Their error handling stays in
        ``authenticate`` because key lookup and refresh failures have distinct
        client-safe outcomes.
        """
        return decode(
            token,
            key=signing_key.key,
            # Defaults match the configuration schema so authenticators saved
            # before optional settings were introduced remain usable.
            algorithms=configuration.get("ALLOWED_ALGORITHMS", ["RS256"]),
            audience=configuration.get("AUDIENCE", ""),
            issuer=configuration.get("ISSUER_URL", ""),
            options={"require": ["exp"]},
            leeway=configuration.get("JWT_CLOCK_SKEW_TOLERANCE_SECONDS", 0),
        )

    def authenticate(self, request: Any = None, *, token: str | None = None, **kwargs: Any) -> BearerAuthenticationResult | None:
        """Validate a bearer token, provision its identity, and apply authenticator maps."""
        # The common authenticator interface supplies the request, but bearer
        # token validation uses only the credential passed by the dispatcher.
        del request
        if token is None or self.database_instance is None:
            logger.debug("External OAuth token is None or database instance is None")
            return None

        logger.debug(f"Attempting to authenticate with external OAuth authenticator {self.database_instance.name}")

        configuration = self.database_instance.configuration
        if not self._matches_token_routing_claims(token, configuration):
            logger.debug(f"External OAuth token does not match authenticator {self.database_instance.name}")
            return None

        logger.debug(f"Validating external OAuth token against authenticator {self.database_instance.name}")
        jwks_uri = configuration.get("JWKS_URI", "")
        if not jwks_uri:
            logger.error(f"External OAuth authenticator {self.database_instance.name} has no configured JWKS URI")
            raise BearerTokenValidationError()

        jwk_client = self._build_jwk_client(jwks_uri, configuration)
        signing_key = self._signing_key_for_token(jwk_client, token)
        claims = self._validated_claims(token, signing_key, jwk_client, configuration)
        user = self._user_from_claims(claims, configuration)
        if user is None:
            return None
        return BearerAuthenticationResult(user=user, auth=ScopedBearerToken(scopes=self._read_write_scopes(claims)))

    def _read_write_scopes(self, claims: dict[str, Any]) -> frozenset[str]:
        """Extract verified read/write scopes, with write implying read."""
        configuration = self.database_instance.configuration
        scope_attribute_name = configuration.get("SCOPE_ATTRIBUTE_NAME", "scope")
        claimed_scopes = claims.get(scope_attribute_name, "")
        if isinstance(claimed_scopes, str):
            scopes = set(claimed_scopes.split())
        elif isinstance(claimed_scopes, list):
            scopes = {scope for scope in claimed_scopes if isinstance(scope, str)}
        else:
            scopes = set()

        user_scopes = set()
        if configuration.get("READ_SCOPE_NAME", "read") in scopes:
            user_scopes.add("read")
        if configuration.get("WRITE_SCOPE_NAME", "write") in scopes:
            user_scopes.update({"read", "write"})

        granted_scopes = frozenset(user_scopes)
        logger.debug(
            f"External OAuth authenticator {self.database_instance.name} mapped scope claim {scope_attribute_name} to API scopes {sorted(granted_scopes)}"
        )
        return granted_scopes

    def _build_jwk_client(self, jwks_uri: str, configuration: dict[str, Any]) -> CachedJWKClient:
        """Create a JWKS client using the provider's explicit TLS and timeout settings."""
        ssl_context = None
        if not configuration.get("VERIFY_SSL", True):
            # This is retained for local development against self-signed IdPs;
            # production endpoints are still constrained to HTTPS by schema validation.
            ssl_context = ssl.create_default_context()  # NOSONAR(S5527) -- this context must disable hostname checks for configured local self-signed IdPs.
            ssl_context.check_hostname = False  # NOSONAR(S5527) -- required with CERT_NONE for configured local self-signed IdPs.
            ssl_context.verify_mode = ssl.CERT_NONE  # NOSONAR(S4830) -- configured local-development support for self-signed IdPs.

        return CachedJWKClient(
            jwks_uri,
            lifespan=configuration.get("JWKS_CACHE_TIMEOUT", 3600),
            timeout=configuration.get("JWKS_URL_TIMEOUT", 30),
            ssl_context=ssl_context,
        )

    def _signing_key_for_token(self, jwk_client: CachedJWKClient, token: str) -> PyJWK:
        """Look up the token key and translate provider errors into safe API failures."""
        try:
            logger.debug(f"Fetching the signing key for external OAuth authenticator {self.database_instance.name}")
            return jwk_client.get_signing_key_from_jwt(token)
        except PyJWKClientConnectionError:
            logger.warning(f"External OAuth JWKS endpoint is unavailable for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError("provider_unavailable") from None
        except PyJWKClientError:
            logger.debug(f"External OAuth signing key lookup rejected a token for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError() from None

    def _validated_claims(self, token: str, signing_key: PyJWK, jwk_client: CachedJWKClient, configuration: dict[str, Any]) -> dict[str, Any]:
        """Verify claims and retry once if an IdP key rotation invalidated the cached key."""
        try:
            logger.debug(f"Fetched signing key for external OAuth authenticator {self.database_instance.name}; validating JWT")
            claims = self._decode_validated_token(token, signing_key, configuration)
            logger.debug(f"External OAuth JWT validated for authenticator {self.database_instance.name}")
            return claims
        except ExpiredSignatureError:
            logger.debug(f"External OAuth token expired for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError("expired") from None
        except InvalidSignatureError:
            return self._validated_claims_after_key_refresh(token, signing_key, jwk_client, configuration)
        except PyJWTError:
            logger.debug(f"External OAuth token validation failed for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError() from None

    def _validated_claims_after_key_refresh(self, token: str, signing_key: PyJWK, jwk_client: CachedJWKClient, configuration: dict[str, Any]) -> dict[str, Any]:
        """Refresh a potentially rotated signing key once, then verify the original JWT again."""
        try:
            logger.debug(f"External OAuth JWT signature failed for authenticator {self.database_instance.name}; refreshing signing key")
            refreshed_signing_key = jwk_client.refresh_signing_key_from_jwt(token)
            if refreshed_signing_key._jwk_data == signing_key._jwk_data:
                raise BearerTokenValidationError()
            return self._decode_validated_token(token, refreshed_signing_key, configuration)
        except ExpiredSignatureError:
            logger.debug(f"External OAuth token expired after key refresh for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError("expired") from None
        except PyJWKClientConnectionError:
            logger.warning(f"External OAuth JWKS endpoint is unavailable during refresh for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError("provider_unavailable") from None
        except (PyJWKClientError, PyJWTError):
            logger.debug(f"External OAuth token validation failed after key refresh for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError() from None

    def _user_from_claims(self, claims: dict[str, Any], configuration: dict[str, Any]) -> AbstractBaseUser | None:
        """Resolve, provision, and map a verified external OAuth identity to an active user."""
        uid = resolve_uid_from_claims(claims, configuration.get("CLAIM_LIST", []))
        if uid is None:
            logger.debug(f"External OAuth token did not contain a configured identity claim for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError()

        email = normalize_and_get_email(claims.get("email")) or ""
        user, _authenticator_user, _created = get_or_create_authenticator_user(
            uid=uid,
            email=email,
            authenticator=self.database_instance,
            user_details={"email": email},
            extra_data=claims,
        )
        if user is None or not user.is_active or is_system_user(user):
            logger.debug(f"External OAuth identity maps to an ineligible user for authenticator {self.database_instance.name}")
            raise BearerTokenValidationError()

        groups = claims.get(configuration.get("GROUPS_CLAIM", "groups"), [])
        if not isinstance(groups, list):
            groups = []
        groups = [group for group in groups if isinstance(group, str)]
        return update_user_claims(user, self.database_instance, groups, attrs=claims)
