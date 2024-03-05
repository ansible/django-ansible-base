import logging

import jwt
from django.utils.translation import gettext_lazy as _
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.oidc')


class OpenIdConnectConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/oidc.html"

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

    PUBLIC_KEY = CharField(
        help_text=_("The public key from your IDP. Only necessary if using keycloak for OIDC."),
        allow_null=True,
        ui_field_label=_('OIDC Public Key'),
    )

    SECRET = CharField(
        help_text=_("'The OIDC secret (Client Secret) from your IDP."),
        allow_null=True,
        ui_field_label=_('OIDC Secret'),
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
