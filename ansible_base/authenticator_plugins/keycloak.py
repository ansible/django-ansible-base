import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from social_core.backends.keycloak import KeycloakOAuth2

from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.serializers.fields import URLField

logger = logging.getLogger('ansible_base.authenticator_plugins.keycloak')


class KeycloakConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/keycloak.html"

    ACCESS_TOKEN_URL = URLField(
        help_text=_("Location where this app can fetch the user's token from."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/token",
        allow_null=False,
    )
    AUTHORIZATION_URL = URLField(
        help_text=_("Location to redirect the user to during the login flow."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/auth",
        allow_null=False,
    )
    KEY = serializers.CharField(help_text=_("Keycloak Client ID."), allow_null=False)
    PUBLIC_KEY = serializers.CharField(help_text=_("RS256 public key provided by your Keycloak ream."), allow_null=False)
    SECRET = serializers.CharField(help_text=_("Keycloak Client secret."), allow_null=True)


class AuthenticatorPlugin(SocialAuthMixin, KeycloakOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = KeycloakConfiguration
    type = "keycloak"
    logger = logger
    category = "sso"
