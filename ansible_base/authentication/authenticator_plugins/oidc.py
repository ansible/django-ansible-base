import logging
import os
import ssl

import jwt
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from jwt import PyJWK, get_unverified_header
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError
from jwt.utils import base64url_decode
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.base import (
    AbstractAuthenticatorPlugin,
    BaseAuthenticatorConfiguration,
    jwks_cache_timeout_field,
    jwks_url_timeout_field,
)
from ansible_base.authentication.jwk_client import DEFAULT_JWKS_CACHE_TIMEOUT, DEFAULT_JWKS_URL_TIMEOUT, CachedJWKClient
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, ChoiceField, DictField, IntegerField, ListField, URLField
from ansible_base.lib.serializers.validators import JWTAlgorithmListFieldValidator
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger("ansible_base.authentication.authenticator_plugins.oidc")


class OpenIdConnectConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/oidc.html"

    #################################
    # Minimal params
    #################################

    OIDC_ENDPOINT = URLField(
        help_text=_("The URL for your OIDC provider including the path up to /.well-known/openid-configuration."),
        allow_null=False,
        ui_field_label=_("OIDC Provider URL"),
    )

    VERIFY_SSL = BooleanField(
        help_text=_("Verify the OIDC provider ssl certificate."),
        default=True,
        allow_null=False,
        ui_field_label=_("Verify OIDC Provider Certificate"),
    )

    KEY = CharField(
        help_text=_("The OIDC key (Client ID) from your IDP. Will also be used as the 'audience' for JWT decoding."),
        allow_null=False,
        ui_field_label=_("OIDC Key"),
    )

    SECRET = CharField(
        help_text=_("'The OIDC secret (Client Secret) from your IDP."),
        allow_null=True,
        ui_field_label=_("OIDC Secret"),
    )

    #################################
    # Additional params
    #################################

    ACCESS_TOKEN_URL = URLField(
        help_text=_("The URL to obtain an access token from the OIDC provider."),
        required=False,
        allow_null=True,
        ui_field_label=_("Access Token URL"),
    )

    ACCESS_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when requesting an access token. Typically 'POST' or 'GET'."),
        default="POST",
        allow_null=True,
        required=False,
        choices=["GET", "PUT", "POST", "PATCH", "DELETE"],
        ui_field_label=_("Access Token Method"),
    )

    AUTHORIZATION_URL = URLField(
        help_text=_("The URL to redirect the user for OIDC provider authorization."),
        required=False,
        allow_null=True,
        ui_field_label=_("Authorization URL"),
    )

    CALLBACK_URL = URLField(
        help_text=_(
            "Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail."
        ),
        required=False,
        allow_null=True,
        ui_field_label=_("OIDC Callback URL"),
    )

    ID_KEY = CharField(
        help_text=_("The JSON key used to extract the user's ID from the ID token."),
        default="sub",
        allow_null=True,
        required=False,
        ui_field_label=_("ID Key"),
    )

    ID_TOKEN_ISSUER = CharField(
        help_text=_("Expected issuer ('iss') of the ID token. If set, it will be used to validate the issuer of the ID token."),
        required=False,
        allow_null=True,
        ui_field_label=_("ID Token Issuer"),
    )

    ID_TOKEN_MAX_AGE = IntegerField(
        help_text=_("The maximum allowed age (in seconds) of the ID token. Tokens older than this will be rejected."),
        default=600,
        allow_null=True,
        validators=[MinValueValidator(0)],
        ui_field_label=_("OIDC Token Max Age"),
    )

    JWT_ALGORITHMS = ListField(
        help_text=_("The algorithm(s) for decoding JWT responses from the IDP."),
        default=OpenIdConnectAuth.JWT_ALGORITHMS,
        allow_null=True,
        validators=[JWTAlgorithmListFieldValidator()],
        ui_field_label=_("OIDC JWT Algorithm(s)"),
    )

    JWT_DECODE_OPTIONS = DictField(
        help_text=_("OIDC JWT decoding options for token validation and processing."),
        default=None,
        allow_null=True,
        ui_field_label=_("OIDC JWT Decode Options."),
    )

    JWKS_URI = URLField(
        help_text=_("The URL to retrieve the provider's public keys for verifying JWT signatures."),
        required=False,
        allow_null=True,
        ui_field_label=_("JWKS URI"),
    )

    JWKS_URL_TIMEOUT = jwks_url_timeout_field()

    JWKS_CACHE_TIMEOUT = jwks_cache_timeout_field()

    PUBLIC_KEY = CharField(
        help_text=_("The public key from your IDP. Only necessary if using keycloak for OIDC."),
        required=False,
        allow_null=True,
        ui_field_label=_("OIDC Public Key"),
    )

    REDIRECT_STATE = BooleanField(
        help_text=_("Enable or disable state parameter in the redirect URI. Recommended to be True for preventing CSRF attacks."),
        default=False,
        allow_null=True,
        ui_field_label=_("Redirect State"),
    )

    REVOKE_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when revoking an access token. Typically 'POST' or 'GET'."),
        default="GET",
        allow_null=True,
        choices=["GET", "PUT", "POST", "PATCH", "DELETE"],
        ui_field_label=_("Revoke Token Method"),
    )

    REVOKE_TOKEN_URL = URLField(
        help_text=_("The URL to revoke tokens. Used in the token revocation flow."),
        required=False,
        allow_null=True,
        ui_field_label=_("Revoke Token URL"),
    )

    RESPONSE_TYPE = CharField(
        help_text=_("The response type the OIDC endpoint should return. Common values are 'code', 'id_token' and 'token'."),
        default="code",
        allow_null=True,
        ui_field_label=_("Response Type"),
    )

    SCOPE = ListField(
        help_text=_('The authorization scope for users. Defaults to ["openid", "profile", "email"].'),
        required=False,
        allow_null=False,
        ui_field_label=_("List of OAuth2 Scope(s)"),
        default=["openid", "profile", "email"],
    )

    TOKEN_ENDPOINT_AUTH_METHOD = CharField(
        help_text=_("The authentication method to use at the token endpoint. Common values are 'client_secret_post', 'client_secret_basic'."),
        required=False,
        allow_null=True,
        ui_field_label=_("Token Endpoint Auth Method"),
    )

    USERINFO_URL = URLField(
        help_text=_("The URL to retrieve user information from the OIDC provider."),
        required=False,
        allow_null=True,
        ui_field_label=_("Userinfo URL"),
    )

    USERNAME_KEY = CharField(
        help_text=_("The JSON key used to extract the user's username from the ID token or userinfo endpoint."),
        default="preferred_username",
        required=False,
        allow_null=True,
        ui_field_label=_("Username Key"),
    )

    GROUPS_CLAIM = CharField(
        help_text=_("The JSON key used to extract the user's groups from the ID token or userinfo endpoint."),
        required=False,
        allow_null=True,
        default="Group",
        ui_field_label=_("Groups Claim"),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, OpenIdConnectAuth, AbstractAuthenticatorPlugin):  # type: ignore[override]
    configuration_class = OpenIdConnectConfiguration
    type = "open_id_connect"
    display_name = _("Generic OIDC")
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ["SECRET"]

    @property
    def groups_claim(self):
        return self.setting("GROUPS_CLAIM")

    def extra_data(self, user, uid, response, details, pipeline_kwargs):
        for perm in ["is_superuser", get_setting("ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG")]:
            if perm in response:
                pipeline_kwargs["social"].extra_data[perm] = response[perm]
        data = super().extra_data(user, uid, response, details, pipeline_kwargs)
        return data

    def get_user_groups(self, extra_groups=[]):
        return extra_groups

    def oidc_config(self):
        # This is a copy of super without caching, which avoids data
        # from one OIDC based authenticator showing up in another
        return self.get_json(self.oidc_endpoint() + "/.well-known/openid-configuration")

    def _jwks_cache_namespace(self) -> str | None:
        """Return a cache namespace tied to this authenticator's persisted configuration version.

        Including ``modified`` means any save -- including enable/disable -- moves
        this authenticator to a new namespace, so earlier key material is no longer
        reachable from any worker. Without a persisted instance, ``CachedJWKClient``
        falls back to scoping the cache by JWKS URI.
        """
        instance = self.database_instance
        if instance is None or getattr(instance, "pk", None) is None:
            return None
        modified = getattr(instance, "modified", None)
        if modified is None:
            return None
        return f"authenticator:{instance.pk}:{modified.isoformat()}"

    def _jwk_client(self) -> CachedJWKClient:
        """Build a JWKS client backed by DAB's shared, Django-cache-backed JWKS cache."""
        return CachedJWKClient(
            self.jwks_uri(),
            cache_namespace=self._jwks_cache_namespace(),
            lifespan=self.setting("JWKS_CACHE_TIMEOUT", DEFAULT_JWKS_CACHE_TIMEOUT),
            timeout=self.setting("JWKS_URL_TIMEOUT", DEFAULT_JWKS_URL_TIMEOUT),
            ssl_context=self._jwks_ssl_context(),
        )

    def _jwks_ssl_context(self) -> ssl.SSLContext | None:
        """Return the TLS context used to fetch JWKS documents.

        social-auth-core fetched JWKS documents through ``requests``, which trusts
        ``REQUESTS_CA_BUNDLE``/``CURL_CA_BUNDLE`` while verification is enabled.
        ``urlopen`` ignores those variables, so load the same bundle explicitly to
        keep trusting identity providers signed by a configured internal CA. Like
        ``requests``, treat a directory value as an OpenSSL ``capath``.
        """
        if not self.setting("VERIFY_SSL", True):
            ssl_context = ssl.create_default_context()  # NOSONAR(S5527) -- this context must disable hostname checks for configured local self-signed IdPs.
            ssl_context.check_hostname = False  # NOSONAR(S5527) -- required with CERT_NONE for configured local self-signed IdPs.
            ssl_context.verify_mode = ssl.CERT_NONE  # NOSONAR(S4830) -- configured local-development support for self-signed IdPs.
            return ssl_context
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
        if ca_bundle:
            if os.path.isdir(ca_bundle):
                return ssl.create_default_context(capath=ca_bundle)
            return ssl.create_default_context(cafile=ca_bundle)
        return None

    @staticmethod
    def _jwk_data(signing_key: PyJWK) -> dict:
        """Return the JSON-safe JWK for a resolved signing key."""
        key = dict(signing_key._jwk_data)
        key.setdefault("alg", signing_key.algorithm_name)
        return key

    @staticmethod
    def _signature_matches(id_token: str, key: dict) -> bool:
        """Return whether ``key`` verifies the signature on ``id_token``."""
        try:
            message, encoded_signature = id_token.rsplit(".", 1)
            signing_key = PyJWK(key)
            decoded_signature = base64url_decode(encoded_signature.encode("utf-8"))
            return signing_key.Algorithm.verify(message.encode("utf-8"), signing_key.key, decoded_signature)
        except (PyJWTError, ValueError):
            return False

    def _find_valid_key_without_kid(self, jwk_client: CachedJWKClient, id_token: str) -> dict | None:
        """Try every provider key when the token header omits ``kid``."""
        for refresh in (False, True):
            try:
                jwk_set = jwk_client.get_jwk_set(refresh=refresh)
            except PyJWKClientConnectionError:
                logger.warning(f"OIDC provider JWKS endpoint is unavailable for authenticator {self.name}")
                return None
            except PyJWTError as e:
                logger.debug(f"Unable to retrieve JWKS keys for authenticator {self.name}: {e}")
                return None
            for signing_key in jwk_set.keys:
                key = self._jwk_data(signing_key)
                if self._signature_matches(id_token, key):
                    return key
        return None

    def find_valid_key(self, id_token):
        """Return the provider key that verifies ``id_token`` using the shared JWKS cache.

        social-auth-core resolves signing keys through ``get_jwks_keys``, whose
        ``@cache(ttl=86400)`` decorator is a module-global, per-process cache keyed
        only by backend class. That shares one authenticator's key material with
        every other Generic OIDC authenticator in the worker and keeps serving
        removed keys when a refresh fails. Resolving keys through
        ``CachedJWKClient`` scopes them to this authenticator's configuration
        version, shares them across workers through Django's cache, and honors
        the configured TTL.

        Returning ``None`` preserves social-auth-core's contract that an unused
        or unverifiable key fails token validation. A failed refresh never falls
        back to previously cached key material.
        """
        try:
            kid = get_unverified_header(id_token).get("kid")
        except PyJWTError as e:
            logger.warning(f"Unable to inspect token header for authenticator {self.name}: {e}")
            return None

        jwk_client = self._jwk_client()
        if kid is None:
            return self._find_valid_key_without_kid(jwk_client, id_token)

        key = None
        try:
            key = self._jwk_data(jwk_client.get_signing_key_from_jwt(id_token))
        except PyJWKClientConnectionError:
            # A forced refresh would only hit the same unreachable endpoint again
            # and can leave a cooldown marker that delays recovery when it returns.
            logger.warning(f"OIDC provider JWKS endpoint is unavailable for authenticator {self.name}")
            return None
        except PyJWTError as e:
            logger.debug(f"No usable cached JWKS key for authenticator {self.name}: {e}")

        if key is None or not self._signature_matches(id_token, key):
            # An unknown kid or a reused kid whose key changed means the provider
            # rotated keys. Force one coordinated refresh and retry validation.
            try:
                key = self._jwk_data(jwk_client.refresh_signing_key_from_jwt(id_token))
            except PyJWKClientConnectionError:
                logger.warning(f"OIDC provider JWKS endpoint is unavailable during refresh for authenticator {self.name}")
                return None
            except PyJWTError as e:
                logger.debug(f"Unable to refresh JWKS keys for authenticator {self.name}: {e}")
                return None

        if self._signature_matches(id_token, key):
            return key
        return None

    def public_key(self):
        key = self.setting("PUBLIC_KEY")
        if key:
            head = "-----BEGIN PUBLIC KEY-----"
            foot = "-----END PUBLIC KEY-----"
            return (
                "\n".join(
                    [
                        head,
                        key,
                        foot,
                    ]
                )
                if head not in key
                else key
            )
        return None

    def user_data(self, access_token, *args, **kwargs):
        """
        This function overrides the one in social auth class OpenIdConnectAuth, since
        it assumes the user info endpoint response returns plain json. Depending on
        server config it may instead be a JWT. This function notices the JWT via the
        content type header and if found, attempts to decode it using the configured
        public key and algorithm(s). None is returned to signify a failed login in the
        case of improper config or other decoding failure.
        """
        user_data = self.request(self.userinfo_url(), headers={"Authorization": f"Bearer {access_token}"})
        if user_data.headers["Content-Type"] == "application/jwt":
            # If the content type is application/jwt than we can assume that the token is encrypted. Otherwise it should be application/json
            pubkey = self.public_key()
            if not pubkey:
                logger.error(_("OIDC client sent encrypted user info response, but no public key found."))
                return None
            try:
                data = jwt.decode(
                    access_token,
                    key=pubkey,
                    algorithms=self.setting("JWT_ALGORITHMS"),
                    audience=self.setting("KEY"),
                )
                return data
            except PyJWTError as e:
                logger.error(_(f"Unable to decode user info response JWT: {e}"))
                return None
        return user_data.json()

    def get_alternative_uid(self, **kwargs):
        preferred_username = kwargs.get("response", {}).get("preferred_username", None)
        uid = kwargs.get("uid", None)

        if preferred_username != uid:
            return preferred_username

        return None
