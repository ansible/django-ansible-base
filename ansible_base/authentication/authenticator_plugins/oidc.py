import logging

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from jwt.algorithms import get_default_algorithms
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, DictField, IntegerField, ListField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.oidc')


DEFAULT_ALGORITHMS = get_default_algorithms()


class JWTAlgorithmListFieldValidator:

    def __init__(self, allowed_values):
        self.allowed_values = allowed_values

    def __call__(self, value):
        if not all(item in self.allowed_values for item in value):
            raise ValidationError(
                _('%(value)s contains items not in the allowed list: %(allowed_values)s'),
                params={'value': value, 'allowed_values': self.allowed_values},
            )


class OpenIdConnectConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/oidc.html"

    #################################
    # Minimal params
    #################################

    OIDC_ENDPOINT = URLField(
        help_text=_("The URL for your OIDC provider including the path up to /.well-known/openid-configuration"),
        allow_null=False,
        ui_field_label=_('OIDC Provider URL'),
    )

    VERIFY_SSL = BooleanField(
        help_text=_("Verify the OIDC provider ssl certificate."),
        default=True,
        allow_null=False,
        ui_field_label=_('Verify OIDC Provider Certificate'),
    )

    KEY = CharField(
        help_text=_("The OIDC key (Client ID) from your IDP. Will also be used as the 'audience' for JWT decoding."),
        allow_null=False,
        ui_field_label=_('OIDC Key'),
    )

    SECRET = CharField(
        help_text=_("'The OIDC secret (Client Secret) from your IDP."),
        allow_null=True,
        ui_field_label=_('OIDC Secret'),
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

    ACCESS_TOKEN_METHOD = CharField(
        help_text=_("The HTTP method to be used when requesting an access token. Typically 'POST' or 'GET'."),
        default="POST",
        allow_null=True,
        required=False,
        ui_field_label=_("Access Token Method"),
    )

    AUTHORIZATION_URL = URLField(
        help_text=_("The URL to redirect the user for OIDC provider authorization."),
        required=False,
        allow_null=True,
        ui_field_label=_("Authorization URL"),
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
        ui_field_label=_('OIDC Token Max Age'),
    )

    JWT_ALGORITHMS = ListField(
        help_text=_("The algorithm(s) for decoding JWT responses from the IDP."),
        default=None,
        allow_null=True,
        validators=[JWTAlgorithmListFieldValidator(list(DEFAULT_ALGORITHMS.keys()))],
        ui_field_label=_('OIDC JWT Algorithm(s)'),
    )

    JWT_DECODE_OPTIONS = DictField(
        help_text=_("OIDC JWT decoding options for token validation and processing"),
        default=None,
        allow_null=True,
        ui_field_label=_('OIDC JWT Decode Options.'),
    )

    JWKS_URI = URLField(
        help_text=_("The URL to retrieve the provider's public keys for verifying JWT signatures."),
        required=False,
        allow_null=True,
        ui_field_label=_("JWKS URI"),
    )

    PUBLIC_KEY = CharField(
        help_text=_("The public key from your IDP. Only necessary if using keycloak for OIDC."),
        required=False,
        allow_null=True,
        ui_field_label=_('OIDC Public Key'),
    )

    REDIRECT_STATE = BooleanField(
        help_text=_("Enable or disable state parameter in the redirect URI. Recommended to be True for preventing CSRF attacks."),
        default=False,
        allow_null=True,
        ui_field_label=_("Redirect State"),
    )

    REVOKE_TOKEN_METHOD = CharField(
        help_text=_("The HTTP method to be used when revoking an access token. Typically 'POST' or 'GET'."),
        default="GET",
        allow_null=True,
        ui_field_label=_("Revoke Token Method"),
    )

    REVOKE_TOKEN_URL = URLField(
        help_text=_("The URL to revoke tokens. Used in the token revocation flow."),
        required=False,
        allow_null=True,
        ui_field_label=_("Revoke Token URL"),
    )

    RESPONSE_TYPE = CharField(
        help_text=_("The authentication method to use at the token endpoint. Common values are 'client_secret_post', 'client_secret_basic'."),
        default="code",
        allow_null=True,
        ui_field_label=_("Token Endpoint Auth Method"),
    )

    SCOPE = ListField(
        help_text=_('The authorization scope for users. Defaults to "read:org".'),
        required=False,
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Scope'),
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


class AuthenticatorPlugin(SocialAuthMixin, OpenIdConnectAuth, AbstractAuthenticatorPlugin):
    configuration_class = OpenIdConnectConfiguration
    type = "open_id_connect"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
