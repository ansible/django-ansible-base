# Installation

TODO

# Usage

TODO

# Writing an Authenticator

## Social Auth

Social Auth backends can be turned into authenticators by subclassing `SocialAuthMixin` and `AbstractAuthenticatorPlugin`
as shown in the example bellow (note that the `SocialAuthMixin` MUST come before KeycloakOauth2 so that the backend's name
gets set correctly):

```python
import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from social_core.backends.keycloak import KeycloakOAuth2

from ansible_base.authentication.utils.authenticator_lib import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.common.serializers.fields import URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.keycloak')


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

    def get_user_groups(self):
        return []
```

In addition to the base classes, each social authenticator must:
- Define a `configuration_class` that subclasses `BaseAuthenticatorConfiguration`. This is a modified DRF serializer
  object is defined in in teh same way.
- Define a plugin type.
- Define `get_user_groups()` (optional): authenticators can add extra logic here to return a list of groups based on
  the attributes returned by their IDP.

## Custom

TODO:
