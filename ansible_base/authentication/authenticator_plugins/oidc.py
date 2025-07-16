import logging

import jwt
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from jwt.algorithms import get_default_algorithms
from jwt.exceptions import PyJWTError
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, ChoiceField, DictField, IntegerField, ListField, URLField
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.oidc')


DEFAULT_ALGORITHMS = get_default_algorithms()


class JWTAlgorithmListFieldValidator:

    allowed_values = list(DEFAULT_ALGORITHMS.keys())

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
        help_text=_("The URL for your OIDC provider including the path up to /.well-known/openid-configuration."),
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

    ACCESS_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when requesting an access token. Typically 'POST' or 'GET'."),
        default="POST",
        allow_null=True,
        required=False,
        choices=['GET', 'PUT', 'POST', 'PATCH', 'DELETE'],
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
        ui_field_label=_('OIDC Token Max Age'),
    )

    JWT_ALGORITHMS = ListField(
        help_text=_("The algorithm(s) for decoding JWT responses from the IDP."),
        default=None,
        allow_null=True,
        validators=[JWTAlgorithmListFieldValidator()],
        ui_field_label=_('OIDC JWT Algorithm(s)'),
    )

    JWT_DECODE_OPTIONS = DictField(
        help_text=_("OIDC JWT decoding options for token validation and processing."),
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

    REVOKE_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when revoking an access token. Typically 'POST' or 'GET'."),
        default="GET",
        allow_null=True,
        choices=['GET', 'PUT', 'POST', 'PATCH', 'DELETE'],
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
        ui_field_label=_('List of OAuth2 Scope(s)'),
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


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, OpenIdConnectAuth, AbstractAuthenticatorPlugin):
    configuration_class = OpenIdConnectConfiguration
    type = "open_id_connect"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']

    @property
    def groups_claim(self):
        return self.setting('GROUPS_CLAIM')

    def extra_data(self, user, backend, response, *args, **kwargs):
        for perm in ["is_superuser", get_setting('ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG')]:
            if perm in response:
                kwargs["social"].extra_data[perm] = response[perm]
        data = super().extra_data(user, backend, response, *args, **kwargs)
        return data

    def get_user_groups(self, extra_groups=[]):
        return extra_groups

    def oidc_config(self):
        # This is a copy of super without caching, which avoids data
        # from one OIDC based authenticator showing up in another
        return self.get_json(self.oidc_endpoint() + "/.well-known/openid-configuration")

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
