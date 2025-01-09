import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.keycloak import KeycloakOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.keycloak')


class KeycloakConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/keycloak.html"

    ACCESS_TOKEN_URL = URLField(
        help_text=_("Location where this app can fetch the user's token from."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/token",
        allow_null=False,
        ui_field_label=_('Keycloak Access Token URL'),
    )
    AUTHORIZATION_URL = URLField(
        help_text=_("Location to redirect the user to during the login flow."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/auth",
        allow_null=False,
        ui_field_label=_('Keycloak Provider URL'),
    )
    KEY = CharField(
        help_text=_("The OIDC key (Client ID) from your Keycloak installation."),
        allow_null=False,
        ui_field_label=_('Keycloak OIDC Key'),
    )
    PUBLIC_KEY = CharField(
        help_text=_("RS256 public key provided by your Keycloak realm."),
        allow_null=False,
        ui_field_label=_('Keycloak Public Key'),
    )
    SECRET = CharField(
        help_text=_("The OIDC secret (Client Secret) from your Keycloak installation."),
        allow_null=True,
        ui_field_label=_('Keycloak OIDC Secret'),
    )

    GROUPS_CLAIM = CharField(
        help_text=_("The JSON key used to extract the user's groups from the ID token or userinfo endpoint."),
        required=False,
        allow_null=True,
        default="Group",
        ui_field_label=_("Groups Claim"),
    )


class AuthenticatorPlugin(SocialAuthMixin, KeycloakOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = KeycloakConfiguration
    type = "keycloak"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']

    @property
    def groups_claim(self):
        return self.setting('GROUPS_CLAIM')

    def extra_data(self, user, backend, response, *args, **kwargs):
        for perm in ["is_superuser", "is_platform_auditor"]:
            if perm in response:
                kwargs["social"].extra_data[perm] = response[perm]
        data = super().extra_data(user, backend, response, *args, **kwargs)
        return data

    def get_user_groups(self, extra_groups=[]):
        return extra_groups

    def get_alternative_uid(self, **kwargs):
        return kwargs.get("response", {}).get("sub", None)
