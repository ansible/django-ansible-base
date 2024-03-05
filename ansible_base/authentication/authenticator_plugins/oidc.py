import logging

import jwt
from django.utils.translation import gettext_lazy as _
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, IntegerField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.oidc')


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

    PUBLIC_KEY = CharField(
        help_text=_("The public key from your IDP. Only necessary if using keycloak for OIDC."),
        default="",
        allow_null=True,
        ui_field_label=_('OIDC Public Key'),
    )

    ALGORITHM = CharField(
        help_text=_("The algorithm for decoding JWT responses from the IDP."),
        default='RS256',
        allow_null=True,
        ui_field_label=_('OIDC JWT Algorithm'),
    )

    ID_TOKEN_MAX_AGE = IntegerField(
        help_text=_("The maximum allowed age (in seconds) of the ID token. Tokens older than this will be rejected."),
        default=600,
        allow_null=True,
        ui_field_label=_('OIDC Token Max Age'),
    )

    REDIRECT_STATE = BooleanField(
        help_text=_("Enable or disable state parameter in the redirect URI. Recommended to be True for preventing CSRF attacks."),
        default=False,
        allow_null=True,
        ui_field_label=_("Redirect State"),
    )

    ACCESS_TOKEN_METHOD = CharField(
        help_text=_("The HTTP method to be used when requesting an access token. Typically 'POST' or 'GET'."),
        default="POST",
        allow_null=True,
        ui_field_label=_("Access Token Method"),
    )

    REVOKE_TOKEN_METHOD = CharField(
        help_text=_("The HTTP method to be used when revoking an access token. Typically 'POST' or 'GET'."),
        default="GET",
        allow_null=True,
        ui_field_label=_("Revoke Token Method"),
    )

    ID_KEY = CharField(
        help_text=_("The JSON key used to extract the user's ID from the ID token."),
        default="sub",
        allow_null=True,
        ui_field_label=_("ID Key"),
    )

    USERNAME_KEY = CharField(
        help_text=_("The JSON key used to extract the user's username from the ID token or userinfo endpoint."),
        default="preferred_username",
        allow_null=True,
        ui_field_label=_("Username Key"),
    )

    ID_TOKEN_ISSUER = CharField(
        help_text=_("Expected issuer ('iss') of the ID token. If set, it will be used to validate the issuer of the ID token."),
        default="",
        allow_null=True,
        ui_field_label=_("ID Token Issuer"),
    )

    ACCESS_TOKEN_URL = URLField(
        help_text=_("The URL to obtain an access token from the OIDC provider."),
        default="",
        allow_null=True,
        ui_field_label=_("Access Token URL"),
    )

    AUTHORIZATION_URL = URLField(
        help_text=_("The URL to redirect the user for OIDC provider authorization."),
        default="",
        allow_null=True,
        ui_field_label=_("Authorization URL"),
    )

    REVOKE_TOKEN_URL = URLField(
        help_text=_("The URL to revoke tokens. Used in the token revocation flow."),
        default="",
        allow_null=True,
        ui_field_label=_("Revoke Token URL"),
    )

    USERINFO_URL = URLField(
        help_text=_("The URL to retrieve user information from the OIDC provider."),
        default="",
        allow_null=True,
        ui_field_label=_("Userinfo URL"),
    )

    JWKS_URI = URLField(
        help_text=_("The URL to retrieve the provider's public keys for verifying JWT signatures."),
        default="",
        allow_null=True,
        ui_field_label=_("JWKS URI"),
    )

    TOKEN_ENDPOINT_AUTH_METHOD = CharField(
        help_text=_("The authentication method to use at the token endpoint. Common values are 'client_secret_post', 'client_secret_basic'."),
        default="",
        allow_null=True,
        ui_field_label=_("Token Endpoint Auth Method"),
    )


class AuthenticatorPlugin(SocialAuthMixin, OpenIdConnectAuth, AbstractAuthenticatorPlugin):
    configuration_class = OpenIdConnectConfiguration
    type = "open_id_connect"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']

    def audience(self):
        return self.setting("KEY")

    def algorithm(self):
        return self.setting("ALGORITHM", default="RS256")

    def public_key(self):
        return "\n".join(
            [
                "-----BEGIN PUBLIC KEY-----",
                self.setting("PUBLIC_KEY"),
                "-----END PUBLIC KEY-----",
            ]
        )

    def get_json(self, url, *args, **kwargs):

        rr = self.request(url, *args, **kwargs)

        # keycloak OIDC returns a JWT encoded JSON blob for the user detail endpoint
        if rr.headers.get('Content-Type') == 'application/jwt':
            return jwt.decode(rr.text, self.public_key(), algorithms=self.algorithm(), audience=self.audience(), options={"verify_signature": True})

        return rr.json()
